import React, { useState, useRef, useEffect, useCallback } from "react";
import "./App.css";

interface Message {
  id: string;
  sender: "user" | "amadeus";
  text: string;
}

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [isRecording, setIsRecording] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Auto-scroll to bottom of chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Handle Text Submission (SSE)
  const handleSubmit = async (e?: React.FormEvent<HTMLFormElement> | React.MouseEvent<HTMLButtonElement>, textInput?: string) => {
    if (e) e.preventDefault();
    const finalInput = textInput || input;
    if (!finalInput.trim() || isTyping) return;

    const userMsg: Message = { id: Date.now().toString(), sender: "user", text: finalInput };
    setMessages((prev: Message[]) => [...prev, userMsg]);
    setIsTyping(true);
    if (!textInput) setInput("");

    const amadeusMsgId = (Date.now() + 1).toString();
    setMessages((prev: Message[]) => [...prev, { id: amadeusMsgId, sender: "amadeus", text: "" }]);

    try {
      const targetUrl = `http://127.0.0.1:8000/api/v1/chat/stream?message=${encodeURIComponent(
        userMsg.text
      )}&source=desktop`;

      const eventSource = new EventSource(targetUrl);

      eventSource.onmessage = (event) => {
        if (event.data === "[DONE]") {
          eventSource.close();
          setIsTyping(false);
          return;
        }

        try {
          const parsed = JSON.parse(event.data);
          if (parsed.delta) {
            setMessages((prev: Message[]) =>
              prev.map((msg: Message) =>
                msg.id === amadeusMsgId ? { ...msg, text: msg.text + parsed.delta } : msg
              )
            );
          }
        } catch (err) {
          console.error("Failed to parse SSE JSON", err);
        }
      };

      eventSource.onerror = (err) => {
        console.error("EventSource failed:", err);
        eventSource.close();
        setIsTyping(false);
      };
    } catch (error) {
      console.error("Chat submission failed", error);
      setIsTyping(false);
    }
  };

  // Handle Voice Recording (WebSocket)
  const toggleRecording = useCallback(async () => {
    if (isRecording) {
      // Stop recording
      mediaRecorderRef.current?.stop();
      wsRef.current?.close();
      setIsRecording(false);
    } else {
      // Start recording
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        mediaRecorderRef.current = mediaRecorder;
        audioChunksRef.current = [];

        // Connect WebSocket
        const ws = new WebSocket("ws://127.0.0.1:8000/api/v1/ws/voice");
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("WebSocket Connected");
          mediaRecorder.start(250); // Send chunks every 250ms
          setIsRecording(true);
        };

        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0 && ws.readyState === WebSocket.OPEN) {
            audioChunksRef.current.push(event.data);
            ws.send(event.data);
          }
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "transcription") {
              console.log("Transcribed:", data.text);
              // Automatically submit the transcribed text to the chat
              if (data.text.trim().length > 0) {
                handleSubmit(undefined, data.text);
              }
            } else if (data.type === "error") {
              console.error("Voice Error:", data.message);
            }
          } catch (e) {
            console.error("Failed to parse WS message", e);
          }
        };

        ws.onerror = (error) => {
          console.error("WebSocket error:", error);
          setIsRecording(false);
          mediaRecorder.stop();
        };

        ws.onclose = () => {
          console.log("WebSocket Closed");
          setIsRecording(false);
        };

      } catch (err) {
        console.error("Microphone access denied or error:", err);
      }
    }
  }, [isRecording]);

  return (
    <div className="jarvis-container">
      <header className="jarvis-header">
        <h1>Amadeus Protocol</h1>
      </header>

      <div className="chat-box">
        {messages.length === 0 && (
          <div className="message amadeus" style={{ opacity: 0.5, fontStyle: "italic", alignSelf: "center" }}>
            Systems online. How can I assist you today, Boss?
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.sender}`}>
            <div className="message-sender">{msg.sender === "user" ? "You" : "Amadeus"}</div>
            <div className="message-content">{msg.text}</div>
          </div>
        ))}
        {isTyping && (
          <div className="message amadeus" style={{ opacity: 0.6 }}>
            <div className="message-sender">Amadeus</div>
            <div className="message-content">...</div>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      <form className="input-area" onSubmit={(e) => handleSubmit(e)}>
        <button
          type="button"
          className={`jarvis-btn ${isRecording ? 'recording' : ''}`}
          onClick={toggleRecording}
          style={{
            padding: '0 15px',
            backgroundColor: isRecording ? 'rgba(255, 50, 50, 0.2)' : 'transparent',
            borderColor: isRecording ? 'rgba(255, 50, 50, 0.6)' : 'var(--glass-border)',
            color: isRecording ? '#ff6b6b' : 'var(--text-secondary)'
          }}
          title="Toggle Voice Transmission"
        >
          {isRecording ? "⏹" : "🎤"}
        </button>
        <input
          type="text"
          className="jarvis-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Command override..."
          disabled={isTyping}
          autoFocus
        />
        <button type="submit" className="jarvis-btn" disabled={isTyping}>
          Transmit
        </button>
      </form>
    </div>
  );
}

export default App;
