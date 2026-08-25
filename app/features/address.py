import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Pre-defined reference corpus of ambiguous Indian address patterns
REFERENCE_CORPUS = [
    "near main road",
    "behind bus stand",
    "house number zero",
    "no address",
    "unknown",
    "xyz",
    "abc",
    "asdfghjkl",
    "test address",
    "opposite railway station",
    "near temple",
    "near mosque",
    "near church",
    "near hospital",
    "near school",
    "village",
    "post office",
    "city",
    "india",
    "room",
    "house",
    "building",
    "street",
    "road",
    "lane"
]

# Singleton instantiation at module level
_vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 4))
# Fit and transform the corpus at process startup
_reference_matrix = _vectorizer.fit_transform(REFERENCE_CORPUS)

def compute_address_ambiguity(address: str) -> float:
    """
    Computes the cosine similarity between the given address and the 
    reference bad address matrix using the pre-fitted TF-IDF vectorizer.
    Returns the maximum similarity score.
    
    (NOTE: The training feature was generated synthetically offline. True TF-IDF 
    parity between training and serving is not in scope for the simulation.)
    """
    if not address or not isinstance(address, str) or len(address.strip()) == 0:
        return 1.0  # High ambiguity for empty or invalid address

    address_vector = _vectorizer.transform([address.lower()])
    similarities = cosine_similarity(address_vector, _reference_matrix)
    
    # Return the max similarity score to any of the ambiguous reference patterns
    return float(np.max(similarities))
