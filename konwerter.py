from nicegui import ui
from nicegui.events import UploadEventArguments
import fitz
import pdfplumber
import os
import re
from datetime import datetime
import hashlib
from nicegui import app

# --- Folders for storing uploaded and output files ---
pdf_folder = 'pdfs'
os.makedirs(pdf_folder, exist_ok=True)
app.add_static_files('/pdfs', pdf_folder)

# --- Globalne zmienne ---
uploaded_file = None
uploaded_filename = ''      # Tu przechowamy oryginalną nazwę z UploadEventArguments.name
markdown_text = "# Upload a PDF file to convert it to Markdown"
display_markdown = True
pdf_url = ''
md_url = ''
original_filename = ''      # Tu przechowamy nazwę pliku używaną w konwersji


# --- Funkcje konwertujące zawartość PDF na Markdown ---
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


def pdf_to_markdown(pdf_path):
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


# --- Logika uploadu i konwersji ---
def convert_and_display_pdf(file_bytes: bytes, original_name: str):
    global markdown_text, pdf_url, md_url, original_filename

    # Oblicz hash zawartości, aby znaleźć (lub utworzyć) unikalny folder
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    pdf_subfolder = os.path.join(pdf_folder, sha256)
    info_path = os.path.join(pdf_subfolder, 'info.txt')

    # Jeśli folder już istnieje, spróbuj odczytać nazwę z info.txt
    if os.path.exists(pdf_subfolder):
        if os.path.exists(info_path):
            with open(info_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('name:'):
                        original_name = line.split(':', 1)[1].strip()
                        break
            original_filename = original_name
            existing_pdf_path = os.path.join(pdf_subfolder, original_name)
            existing_md_path = os.path.join(pdf_subfolder, os.path.splitext(original_name)[0] + '.md')

            # Jeśli zarówno PDF, jak i MD istnieją, wczytaj MD i ustaw URL-e
            if os.path.exists(existing_pdf_path) and os.path.exists(existing_md_path):
                with open(existing_md_path, 'r', encoding='utf-8') as md_file:
                    markdown_text = md_file.read()
                pdf_url = f'/pdfs/{sha256}/{original_name}'
                md_url = f'/pdfs/{sha256}/{os.path.basename(existing_md_path)}'
                return

    # Jeżeli tu dochodzimy – folder nie istniał lub brakowało pliku, więc tworzymy nowy
    os.makedirs(pdf_subfolder, exist_ok=True)
    pdf_path = os.path.join(pdf_subfolder, original_name)
    with open(pdf_path, 'wb') as f:
        f.write(file_bytes)

    # Zapisujemy oryginalną nazwę w info.txt w formacie "name: <nazwa>"
    with open(info_path, 'w', encoding='utf-8') as f:
        f.write(f'name: {original_name}')

    original_filename = original_name
    markdown_text = pdf_to_markdown(pdf_path)

    # Zapis Markdown’a
    md_filename = os.path.splitext(original_name)[0] + '.md'
    md_path = os.path.join(pdf_subfolder, md_filename)
    with open(md_path, 'w', encoding='utf-8') as md_file:
        md_file.write(markdown_text)

    pdf_url = f'/pdfs/{sha256}/{original_name}'
    md_url = f'/pdfs/{sha256}/{md_filename}'


def on_upload(e: UploadEventArguments):
    global uploaded_file, uploaded_filename
    if e.name.lower().endswith('.pdf'):
        uploaded_file = e.content.read()
        uploaded_filename = e.name  # Rzeczywista nazwa z klienta
        upload_button.enable()
        ui.notify(f'File "{e.name}" uploaded successfully.', type='success')
    else:
        ui.notify('Only .pdf files are allowed', type='warning')
        upload_button.disable()


def on_click_upload():
    global uploaded_file, uploaded_filename
    if not uploaded_file:
        ui.notify('Please upload a PDF file first.', type='warning')
        return

    try:
        # Przekazujemy tutaj prawdziwą nazwę (nie "uploaded.pdf")
        convert_and_display_pdf(uploaded_file, uploaded_filename)
        update_display()
    except Exception as e:
        ui.notify(f"Conversion error: {e}", type='error')


def update_display():
    # Wyświetlamy oryginalną nazwę pliku nad PDF-em
    filename_label.text = f"Oryginalny plik: {original_filename}"
    filename_label.update()

    markdown_output.set_content(markdown_text if display_markdown else f"```\n{markdown_text}\n```")
    markdown_output.update()
    if pdf_url:
        pdf_iframe.props['src'] = pdf_url
        pdf_iframe.update()
    if md_url:
        download_button.enable()


# --- UI ---
with ui.card().classes('w-full max-w-3xl'):
    ui.label('Upload a PDF file')
    filename_label = ui.label('')  # Tu pokażemy oryginalną nazwę po konwersji

    ui.upload(
        label='Choose PDF',
        on_upload=on_upload,
        auto_upload=True,
        max_files=1,
    ).props('accept=.pdf')

    upload_button = ui.button('Convert to Markdown', on_click=on_click_upload)
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

    markdown_output = ui.markdown(markdown_text if display_markdown else f"```\n{markdown_text}\n```")

ui.run()
