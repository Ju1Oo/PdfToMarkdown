from nicegui import ui
from nicegui.events import UploadEventArguments
import fitz  
import pdfplumber
import os
import re
from datetime import datetime
import hashlib
import json

# --- Folders for storing uploaded and output files ---
pdf_folder = 'pdfs'
os.makedirs(pdf_folder, exist_ok=True)

from nicegui import app
app.add_static_files('/pdfs', pdf_folder)

uploaded_file = None
original_filename = None
markdown_text = "# Upload a PDF file to convert it to Markdown"
html_text = ""
display_markdown = True
pdf_url = ''
md_url = ''
html_url = ''

# --- Conversion functions ---
def format_text_block_to_markdown(block):
    markdown = ""
    for line in block["lines"]:
        for span in line["spans"]:
            text = span["text"].strip()
            if not text:
                continue
            size = span["size"]
            if size > 16:
                markdown += f"\n# {text}\n"
            elif size > 13:
                markdown += f"\n## {text}\n"
            elif size > 11:
                markdown += f"\n### {text}\n"
            else:
                if re.match(r"^[•\-–●]\s+", text):
                    markdown += f"- {text[2:].strip()}\n"
                elif re.match(r"^\d+\.\s+", text):
                    markdown += f"{text}\n"
                else:
                    markdown += f"{text} "
        markdown += "\n"
    return markdown

def table_to_markdown(table):
    if not table or not table[0]:
        return ""
    clean_table = [[str(cell) if cell is not None else "" for cell in row] for row in table]
    header = clean_table[0]
    md = "| " + " | ".join(header) + " |\n"
    md += "| " + " | ".join(["---"] * len(header)) + " |\n"
    for row in clean_table[1:]:
        md += "| " + " | ".join(row) + " |\n"
    return md + "\n"

def get_tables_with_bbox(plumber_page):
    tables_info = []
    for table_obj in plumber_page.find_tables():
        bbox = table_obj.bbox
        rows = table_obj.extract()
        tables_info.append({"bbox": bbox, "data": rows})
    return tables_info

def bbox_intersects(b1, b2):
    return not (b1[2] <= b2[0] or b1[0] >= b2[2] or b1[3] <= b2[1] or b1[1] >= b2[3])

def pdf_to_markdown(pdf_path, output_folder):
    doc = fitz.open(pdf_path)
    plumber_pdf = pdfplumber.open(pdf_path)

    output = []
    total_pages = len(doc)

    for page_num in range(total_pages):
        output.append(f"\n\n---\n\n## Strona {page_num + 1}\n\n")

        mu_page = doc[page_num]
        plumber_page = plumber_pdf.pages[page_num]
        blocks = mu_page.get_text("dict")["blocks"]
        tables_info = get_tables_with_bbox(plumber_page)

        items = []
        for block in blocks:
            if block["type"] != 0:
                continue
            block_bbox = block["bbox"]
            if any(bbox_intersects(block_bbox, tbl["bbox"]) for tbl in tables_info):
                continue
            items.append({"type": "text", "bbox": block_bbox, "content": block})

        for tbl in tables_info:
            items.append({"type": "table", "bbox": tbl["bbox"], "content": tbl["data"]})

        items.sort(key=lambda it: it["bbox"][1])

        for it in items:
            if it["type"] == "text":
                output.append(format_text_block_to_markdown(it["content"]))
            elif it["type"] == "table":
                output.append("\n**Tabela:**\n\n")
                output.append(table_to_markdown(it["content"]))

    plumber_pdf.close()
    doc.close()
    return ''.join(output)

def pdf_to_html(pdf_path):
    doc = fitz.open(pdf_path)
    html_pages = []
    for page in doc:
        html_pages.append(page.get_text("html"))
    doc.close()
    # Złącz wszystkie strony w jeden plik HTML
    full_html = "<html><body>\n" + "\n<hr>\n".join(html_pages) + "\n</body></html>"
    return full_html

# --- Utility: hash content of file bytes ---
def hash_bytes(content_bytes):
    return hashlib.sha256(content_bytes).hexdigest()

# --- Handling of upload and conversion ---
def convert_and_display_pdf(file_bytes: bytes, original_name: str):
    global markdown_text, pdf_url, md_url, html_text, html_url

    file_hash = hash_bytes(file_bytes)
    pdf_subfolder = os.path.join(pdf_folder, file_hash)
    os.makedirs(pdf_subfolder, exist_ok=True)

    pdf_path = os.path.join(pdf_subfolder, original_name)
    info_json_path = os.path.join(pdf_subfolder, 'info.json')

    if os.path.exists(pdf_path) and os.path.exists(info_json_path):
        with open(info_json_path, 'r', encoding='utf-8') as f:
            info_data = json.load(f)
        md_filename = os.path.splitext(info_data.get("name", original_name))[0] + '.md'
        md_path = os.path.join(pdf_subfolder, md_filename)
        with open(md_path, 'r', encoding='utf-8') as md_file:
            markdown_text = md_file.read()
        pdf_url = f'/pdfs/{file_hash}/{info_data.get("name", original_name)}'
        md_url = f'/pdfs/{file_hash}/{md_filename}'

        # Wczytaj plik html jeśli istnieje
        html_filename = os.path.splitext(info_data.get("name", original_name))[0] + '.html'
        html_path = os.path.join(pdf_subfolder, html_filename)
        if os.path.exists(html_path):
            with open(html_path, 'r', encoding='utf-8') as html_file:
                html_text = html_file.read()
            html_url = f'/pdfs/{file_hash}/{html_filename}'
        else:
            html_text = ""
            html_url = ''
        return

    with open(pdf_path, 'wb') as f:
        f.write(file_bytes)

    info_data = {
        "name": original_name,
        "uploaded_at": datetime.now().isoformat(timespec='seconds'),
        "size_bytes": len(file_bytes)
    }
    with open(info_json_path, 'w', encoding='utf-8') as f:
        json.dump(info_data, f, indent=2, ensure_ascii=False)

    markdown_text = pdf_to_markdown(pdf_path, pdf_subfolder)
    html_text = pdf_to_html(pdf_path)

    pdf_url = f'/pdfs/{file_hash}/{original_name}'

    md_filename = os.path.splitext(original_name)[0] + '.md'
    md_path = os.path.join(pdf_subfolder, md_filename)
    with open(md_path, 'w', encoding='utf-8') as md_file:
        md_file.write(markdown_text)
    md_url = f'/pdfs/{file_hash}/{md_filename}'

    html_filename = os.path.splitext(original_name)[0] + '.html'
    html_path = os.path.join(pdf_subfolder, html_filename)
    with open(html_path, 'w', encoding='utf-8') as html_file:
        html_file.write(html_text)
    html_url = f'/pdfs/{file_hash}/{html_filename}'

def on_upload(e: UploadEventArguments):
    global uploaded_file, original_filename
    if e.name.endswith('.pdf'):
        uploaded_file = e.content.read()
        original_filename = e.name
        upload_button.enable()
        ui.notify(f'File "{e.name}" uploaded successfully.', type='success')
        print(f"Uploaded file size: {len(uploaded_file)} bytes")
    else:
        ui.notify('Only .pdf files are allowed', type='warning')
        upload_button.disable()
        print(f"Rejected file upload: {e.name}")

def on_click_upload():
    global uploaded_file, original_filename
    if not uploaded_file or not original_filename:
        ui.notify('Please upload a PDF file first.', type='warning')
        return

    try:
        convert_and_display_pdf(uploaded_file, original_filename)
        update_display()
    except Exception as e:
        ui.notify(f"Conversion error: {e}", type='error')

def update_display():
    markdown_output.set_content(markdown_text if display_markdown else f"```\n{markdown_text}\n```")
    markdown_output.update()
    if pdf_url:
        pdf_iframe.props['src'] = pdf_url
        pdf_iframe.update()
    if md_url:
        download_button.enable()
    if html_url:
        download_html_button.enable()

# --- UI ---
with ui.card().classes('w-full max-w-3xl'):
    ui.label('Upload a PDF file')

    ui.upload(
        label='Choose PDF',
        on_upload=on_upload,
        auto_upload=True,
        max_files=1,
    ).props('accept=.pdf')

    upload_button = ui.button('Convert to Markdown & HTML', on_click=on_click_upload)
    upload_button.disable()

    ui.separator()

    with ui.element('div').classes('w-full h-96') as pdf_display:
        with ui.element('iframe').classes('w-full h-full').props(f'src={pdf_url}') as pdf_iframe:
            pass

    def toggle_view():
        global display_markdown
        display_markdown = not display_markdown
        toggle_button.text = 'Switch to ' + ('markdown' if display_markdown else 'raw')
        update_display()

    toggle_button = ui.button('Switch to markdown', on_click=toggle_view)
    download_button = ui.button('Download Markdown', on_click=lambda: ui.download(md_url, 'converted.md'))
    download_button.disable()
    download_html_button = ui.button('Download HTML', on_click=lambda: ui.download(html_url, 'converted.html'))
    download_html_button.disable()

    markdown_output = ui.markdown(markdown_text if display_markdown else f"```\n{markdown_text}\n```")

ui.run()
