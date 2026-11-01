# utils.py
import uuid
import hashlib
import warnings
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

# Algunos resúmenes son solo una URL; BeautifulSoup avisa, pero no es un error.
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

# normalize_url, clean_html y entry_text son copia exacta de las de
# clasificacion/tools/collect_dataset.py: el modelo debe ver en producción el mismo
# texto que vio al entrenar (docs/eventos.md, regla 7). Si cambian allá, cambiarlas aquí.


def normalize_url(url: str) -> str:
    """Misma normalización que el recolector: sin utm_*, fbclid, fragmento ni / final."""
    s = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(s.query) if not k.startswith("utm_") and k not in ("fbclid", "gclid")]
    path = s.path.rstrip("/") or "/"
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), path, urlencode(query), ""))


def clean_html(html: str) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())


def entry_text(entry) -> str:
    """Título + el texto más largo disponible (contenido completo o resumen)."""
    title, body = entry_title_body(entry)
    return f"{title}. {body}".strip() if body else title


def entry_title_body(entry) -> tuple[str, str]:
    """Separa lo que entry_text une: title + ". " + body == entry_text(entry).

    Son los campos `title` y `body` de article.ingested; Clasificación predice sobre
    title + ". " + body, igual que el recolector del dataset.
    """
    parts = [c.get("value", "") for c in entry.get("content", [])] + [entry.get("summary", "")]
    body = max((clean_html(p) for p in parts), key=len, default="")
    title = " ".join(entry.get("title", "").split())
    return title, body


def entry_date(entry) -> str | None:
    """Fecha de publicación en ISO 8601 UTC con Z (igual que el recolector)."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def entry_image(entry: dict) -> str | None:
    """
    Extrae la URL de la imagen principal usando heurísticas y BeautifulSoup,
    revisando media_content, enclosures y tags <img>.
    """
    image_url = None
    
    # 1. Buscar en media_content
    if 'media_content' in entry and len(entry.media_content) > 0:
        image_url = entry.media_content[0].get('url')
        
    # 2. Buscar en media_thumbnail si no hay media_content
    elif 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
        image_url = entry.media_thumbnail[0].get('url')
        
    # 3. Buscar en enclosures (links adjuntos al RSS, típicamente imágenes)
    elif 'links' in entry:
        for link in entry.links:
            if link.get('rel') == 'enclosure' and 'image' in link.get('type', ''):
                image_url = link.get('href')
                break

    # 4. Buscar tag <img> dentro del summary o content
    if not image_url:
        html_to_check = ""
        if 'content' in entry and len(entry.content) > 0:
            html_to_check = entry.content[0].value
        elif 'summary' in entry:
            html_to_check = entry.summary
            
        if html_to_check:
            soup = BeautifulSoup(html_to_check, "html.parser")
            img_tag = soup.find('img')
            if img_tag and img_tag.get('src'):
                image_url = img_tag.get('src')

    # Retornar validando que comience por HTTPS
    if image_url and image_url.startswith("https://"):
        return image_url
    return None

def generate_article_id(normalized_url: str) -> str:
    """Genera un ID único para el artículo usando UUID5 basado en la URL normalizada."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, normalized_url))

def generate_hash(title: str, body: str) -> str:
    """Genera un hash SHA-256 para detectar modificaciones de contenido."""
    content = f"{title}\n{body}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()