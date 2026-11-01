# utils.py
import uuid
import hashlib
import re
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup

def normalize_url(url: str) -> str:
    """
    Normaliza una URL eliminando parámetros de rastreo (utm) y fragmentos.
    Garantiza compatibilidad estricta con el sistema original.
    """
    if not url:
        return ""
    parsed = urlparse(url.strip())
    # Limpiar query params de utm_
    query_parts = parsed.query.split('&')
    clean_query = '&'.join([q for q in query_parts if not q.startswith('utm_') and q])
    # Reconstruir URL sin fragmento (#)
    normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, clean_query, ''))
    return normalized.rstrip('/')

def clean_html(html_content: str) -> str:
    """
    Limpia tags HTML de un texto sin unir palabras juntas.
    """
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=" ", strip=True)

def entry_text(entry: dict, title: str) -> str:
    """
    Extrae el texto de la noticia priorizando content sobre summary.
    No añade puntos finales al título y se asegura de no repetir el título en el cuerpo.
    """
    body_html = ""
    if 'content' in entry and len(entry.content) > 0:
        body_html = entry.content[0].value
    elif 'summary' in entry:
        body_html = entry.summary
        
    cleaned_body = clean_html(body_html)
    
    # Evitar repetir el título al inicio del cuerpo
    if cleaned_body.startswith(title):
        cleaned_body = cleaned_body[len(title):].strip()
        
    # Eliminar puntuación inicial sobrante tras remover el título
    cleaned_body = re.sub(r'^[^\w\s]+', '', cleaned_body).strip()
    return cleaned_body

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