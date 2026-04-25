import sys
import os

# Add src to path
sys.path.append(os.path.abspath("src"))

try:
    import numpy as np
    print(f"Numpy version: {np.__version__}")
    print(f"Numpy ndarray: {np.ndarray}")
    print(f"Numpy file: {np.__file__}")
    
    from sentence_transformers import SentenceTransformer
    print("Successfully imported SentenceTransformer")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
