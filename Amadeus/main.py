# main.py

import sys
from amadeus import Amadeus # Import our new class

def main():
    """
    Main function to initialize and run the Amadeus assistant.
    """
    # Check for debug mode flag (e.g., python main.py --debug)
    debug_mode = "--debug" in sys.argv or "-d" in sys.argv
    
    if debug_mode:
        print("Starting Amadeus in DEBUG MODE (text input instead of voice)")
    
    try:
        # Create an instance of the assistant
        assistant = Amadeus(debug_mode=debug_mode)
        
        # Start the assistant's main loop
        assistant.start()
        
    except Exception as e:
        print(f"A critical error occurred: {e}")
        # Optionally, log the full traceback for debugging
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()