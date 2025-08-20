import unicodedata
import spacy
from spacy.cli import download

SPACY_MODELS = {
    "es": "es_core_news_md",
    "en": "en_core_web_md"
}

nlp_es = None
try:
    nlp_es = spacy.load(SPACY_MODELS["es"])
except Exception as e:
    print(f"Downloading {SPACY_MODELS['es']} model...")
    download(SPACY_MODELS['es'])
    nlp_es = spacy.load(SPACY_MODELS['es'])

nlp_en = None
try:
    nlp_en = spacy.load(SPACY_MODELS["en"])
except Exception as e:
    print(f"Downloading {SPACY_MODELS['en']} model...")
    download(SPACY_MODELS['en'])
    nlp_en = spacy.load(SPACY_MODELS['en'])

async def normalize_content(text):
    """
    Normalizes the input text by removing accents and converting to lowercase.
    """
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.lower()

async def preprocess_content(content: str, lang: str = "es") -> str:
    """
    Tokenizes the input content using spaCy, removing punctuation, stop words, and spaces.
    Returns a list of lemmatized tokens in lowercase.
    """
    nlp = nlp_es if lang == "es" else nlp_en
    tokens = [
        normalize_content(token.lemma_)
        for token in nlp(content)
        if not token.is_punct and not token.is_stop and not token.is_space
    ]
    return " ".join(tokens)