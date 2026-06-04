import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List, Dict
import json
from pathlib import Path

# Load model once at module level
_model = None
_skill_embeddings_cache = {}

def get_model():
    global _model
    if _model is None:
        print("📥 Loading sentence-transformers model: all-MiniLM-L6-v2...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✅ Model loaded successfully")
    return _model


def load_skill_embeddings_from_so_data(so_profiles: List[Dict] = None):
    """
    Load and cache skill embeddings from Stack Overflow survey data.
    This enriches the model with real-world skill co-occurrence patterns.
    """
    global _skill_embeddings_cache
    
    if so_profiles is None:
        return _skill_embeddings_cache
    
    print(f"📊 Loading skill embeddings from {len(so_profiles)} SO profiles...")
    model = get_model()
    
    # Collect all unique skills from SO data
    all_skills = set()
    for profile in so_profiles:
        all_skills.update(profile.get('skill_tags', []))
    
    # Pre-encode skills for faster matching
    for skill in all_skills:
        if skill not in _skill_embeddings_cache:
            _skill_embeddings_cache[skill] = model.encode([skill], convert_to_numpy=True)[0]
    
    print(f"✅ Cached {len(_skill_embeddings_cache)} skill embeddings from SO data")
    return _skill_embeddings_cache


def compute_similarity(task_description: str, skill_tags: List[str]) -> float:
    """
    Compute cosine similarity between task description and skill tags.
    Uses Stack Overflow skill embeddings if available for better accuracy.
    Returns a float between 0.0 and 1.0.
    """
    model = get_model()

    # Encode task description
    task_embedding = model.encode([task_description], convert_to_numpy=True)[0]

    # Build skill embedding using cached SO embeddings where available
    skill_embeddings = []
    for skill in skill_tags:
        if skill in _skill_embeddings_cache:
            skill_embeddings.append(_skill_embeddings_cache[skill])
        else:
            # Fall back to on-the-fly encoding
            skill_embeddings.append(model.encode([skill], convert_to_numpy=True)[0])
    
    # Average skill embeddings
    if skill_embeddings:
        skill_embedding = np.mean(skill_embeddings, axis=0)
    else:
        skill_embedding = np.zeros_like(task_embedding)

    # Compute cosine similarity
    similarity = float(np.dot(task_embedding, skill_embedding) / (
        np.linalg.norm(task_embedding) * np.linalg.norm(skill_embedding) + 1e-8
    ))

    # Normalise to 0-1 range (similarity is already between -1 and 1, we clip to 0-1)
    return max(0.0, min(1.0, similarity))


def rank_developers_by_nlp(task_description: str, developers: List[dict]) -> List[dict]:
    """
    Rank developers by NLP similarity score (descending).
    Each developer must have: { id, skillTags }
    """
    results = []

    for dev in developers:
        skill_tags = dev.get('skillTags', [])
        score = compute_similarity(task_description, skill_tags)
        results.append({
            'id': dev.get('id', ''),
            'nlp_score': score,
        })

    # Sort by NLP score descending
    results.sort(key=lambda x: x['nlp_score'], reverse=True)
    return results


def encode_texts(texts: List[str]) -> np.ndarray:
    """Encode a list of texts into embeddings."""
    model = get_model()
    return model.encode(texts, convert_to_numpy=True)