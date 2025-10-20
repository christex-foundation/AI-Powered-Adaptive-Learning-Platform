import os
import sys
import io
import json
import hashlib
from pathlib import Path
from datetime import datetime
import glob
import warnings
import logging
from typing import Dict, Any, Tuple

# Clean up environment to suppress warnings/logs
sys.stderr = io.StringIO()
os.environ["USER_AGENT"] = "Mozilla/5.0 (compatible; YourBot/1.0)"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader

# ----------------------------
# CLEAN TERMINAL OUTPUT
# ----------------------------
warnings.filterwarnings("ignore", category=UserWarning)
logging.getLogger("PyPDF2").setLevel(logging.ERROR)

# ----------------------------
# CONFIGURATION
# ----------------------------
CURRICULUM_ROOT = "curriculum_data"
VECTORSTORE_ROOT = "vectorstores"
METADATA_FILE = "vectorstore_metadata.json"

# Global dictionary to hold all initialized vectorstores
GLOBAL_VECTORSTORES: Dict[str, Any] = {}

# ----------------------------
# METADATA MANAGEMENT
# ----------------------------
def get_folder_hash(folder_path):
    """Generate hash of all PDFs in a subject folder."""
    hash_md5 = hashlib.md5()
    pdf_files = sorted(glob.glob(os.path.join(folder_path, "*.pdf")))
    
    for pdf_path in pdf_files:
        hash_md5.update(Path(pdf_path).name.encode())
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_metadata(subject_name):
    """Load or initialize metadata for a specific subject's vectorstore"""
    metadata_path = Path(VECTORSTORE_ROOT) / f"{subject_name}_faiss" / METADATA_FILE
    if metadata_path.exists():
        try:
            with open(metadata_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_metadata(subject_name, files_hash, num_documents, num_chunks):
    """Save metadata after a successful build"""
    subject_faiss_dir = Path(VECTORSTORE_ROOT) / f"{subject_name}_faiss"
    metadata_path = subject_faiss_dir / METADATA_FILE
    
    metadata = {
        "file_hash": files_hash,
        "num_documents": num_documents,
        "num_chunks": num_chunks,
        "last_build": datetime.now().isoformat()
    }
    # Ensure the subject's vectorstore path exists before saving metadata
    subject_faiss_dir.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=4)
    return metadata

def should_rebuild_vectorstore(subject_name):
    """Check if the vectorstore exists and if the source files have changed for a specific subject."""
    subject_path = Path(CURRICULUM_ROOT) / subject_name
    vectorstore_path = Path(VECTORSTORE_ROOT) / f"{subject_name}_faiss"

    # Check if the FAISS index files exist
    if not (vectorstore_path / "index.faiss").exists() or not (vectorstore_path / "index.pkl").exists():
        print(f"💡 Vectorstore index files missing for {subject_name}. Rebuilding.")
        return True
    
    current_hash = get_folder_hash(subject_path)
    metadata = get_metadata(subject_name)
    
    # Check if hash is missing or mismatched
    if metadata.get("file_hash") != current_hash:
        print(f"💡 File hash mismatch for {subject_name}. Rebuilding vectorstore.")
        return True
    
    return False

# ----------------------------
# CORE RAG FUNCTIONS
# ----------------------------

def create_embeddings():
    """Initialize the HuggingFace Embeddings model."""
    return HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")

def build_vectorstore(subject_name) -> Tuple[Any, Any]:
    """Load PDFs for a subject, chunk, and build the FAISS vectorstore."""
    subject_folder = Path(CURRICULUM_ROOT) / subject_name
    vectorstore_path_str = str(Path(VECTORSTORE_ROOT) / f"{subject_name}_faiss")
    
    print("\n" + "=" * 80)
    print(f"🧠 BUILDING NEW VECTORSTORE for {subject_name.upper()}")
    print("=" * 80)
    
    if not subject_folder.is_dir():
        print(f"❌ Error: Subject folder not found at '{subject_folder}'")
        return None, None
        
    all_documents = []
    pdf_files = sorted(glob.glob(os.path.join(subject_folder, "*.pdf")))
    
    for pdf_file in pdf_files:
        try:
            loader = PyPDFLoader(pdf_file)
            documents = loader.load()
            all_documents.extend(documents)
            print(f"📄 Loaded {Path(pdf_file).name} ({len(documents)} pages)")
        except Exception as e:
            print(f"⚠️ Could not load PDF {Path(pdf_file).name}: {e}")

    if not all_documents:
        print("❌ No documents loaded. Vectorstore build failed.")
        return None, None

    # 2. Split documents into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len
    )
    text_chunks = text_splitter.split_documents(all_documents)
    print(f"✂️ Split into {len(text_chunks)} chunks for RAG")

    # 3. Create embeddings and vectorstore
    try:
        embeddings = create_embeddings()
        vectorstore = FAISS.from_documents(text_chunks, embeddings)
        print("✅ Embeddings created.")

        # 4. Save
        Path(vectorstore_path_str).mkdir(parents=True, exist_ok=True) 
        vectorstore.save_local(vectorstore_path_str)
        print(f"💾 Vectorstore saved to {vectorstore_path_str}")
        
        # Save metadata only if save_local succeeds
        files_hash = get_folder_hash(subject_folder)
        metadata = save_metadata(subject_name, files_hash, len(all_documents), len(text_chunks))
        print(f"📝 Metadata saved: {metadata['num_chunks']} chunks, built at {metadata['last_build']}")

    except Exception as e:
        print(f"❌ CRITICAL ERROR during build process for {subject_name}: {e}")
        return None, None

    print("=" * 80 + "\n")
    return vectorstore, embeddings


def load_vectorstore(subject_name) -> Tuple[Any, Any]:
    """Load existing vectorstore from disk for a specific subject"""
    vectorstore_path_str = str(Path(VECTORSTORE_ROOT) / f"{subject_name}_faiss")
    
    print("\n" + "=" * 80)
    print(f"⚡ LOADING CACHED VECTORSTORE for {subject_name.upper()}")
    print("=" * 80)
    
    if not (Path(vectorstore_path_str) / "index.faiss").exists():
        print(f"⚠️  Cached index file missing for {subject_name}. Forcing rebuild.")
        return build_vectorstore(subject_name)
        
    try:
        embeddings = create_embeddings()
        vectorstore = FAISS.load_local(
            vectorstore_path_str,
            embeddings,
            allow_dangerous_deserialization=True
        )

        metadata = get_metadata(subject_name)
        if metadata:
            print(f"📊 Loaded vectorstore with {metadata.get('num_chunks', 'N/A')} chunks")
            print(f"📅 Last built: {metadata.get('last_build', 'N/A')}")

        print("✅ Vectorstore loaded successfully!")
    except Exception as e:
        print(f"❌ Error loading vectorstore for {subject_name}: {e}. Attempting rebuild.")
        return build_vectorstore(subject_name)

    print("=" * 80 + "\n")
    return vectorstore, embeddings


def initialize_vectorstore(subject_name, force_rebuild=False) -> Tuple[Any, Any]:
    """Initialize vectorstore with caching for a specific subject"""
    if subject_name in GLOBAL_VECTORSTORES and not force_rebuild:
        return GLOBAL_VECTORSTORES[subject_name], create_embeddings() # Return cached

    if force_rebuild or should_rebuild_vectorstore(subject_name):
        return build_vectorstore(subject_name)
    else:
        return load_vectorstore(subject_name)


def get_available_subjects() -> list:
    """Return a list of subfolders (subjects) found in the curriculum root."""
    if not Path(CURRICULUM_ROOT).exists():
        return []
    
    subjects = [
        d.name for d in Path(CURRICULUM_ROOT).iterdir()
        if d.is_dir() and any(d.glob("*.pdf"))
    ]
    return sorted(subjects)


def initialize_all_vectorstores():
    """
    Quick check of available subjects WITHOUT initializing them.
    Actual initialization happens on first use (lazy loading).
    """
    global GLOBAL_VECTORSTORES
    subjects = get_available_subjects()
    
    print("\n" + "#" * 80)
    print("📦 DISCOVERED CURRICULUM SUBJECTS (Lazy Loading Enabled)")
    print("#" * 80)
    print(f"✓ Found {len(subjects)} subject(s): {', '.join(subjects)}")
    print("ℹ️  Vectorstores will initialize on first request (lazy loading)")
    print("#" * 80 + "\n")

    return subjects

# Initialize on import (just discovers subjects, doesn't load vectorstores)
AVAILABLE_SUBJECTS = initialize_all_vectorstores()