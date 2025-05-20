from nicegui import ui
from nicegui.events import UploadEventArguments
import fitz  
import pdfplumber
import os
import re
from datetime import datetime

# --- Folders for storing uploaded and output files ---
pdf_folder = 'pdfs'
os.makedirs(pdf_folder, exist_ok=True)
from nicegui import app
app.add_static_files('/pdfs', pdf_folder)



uploaded_file = None
markdown_text = "# Upload a PDF file to convert it to Markdown"
display_markdown = True
pdf_url = ''
md_url = ''


# --- Conversion functions---
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


# --- Handling of upload and conversion ---
def convert_and_display_pdf(file_bytes: bytes, original_name: str):
    global markdown_text, pdf_url, md_url

    file_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_subfolder = os.path.join(pdf_folder, file_id)
    os.makedirs(pdf_subfolder, exist_ok=True)

    pdf_path = os.path.join(pdf_subfolder, original_name)
    with open(pdf_path, 'wb') as f:
        f.write(file_bytes)

    markdown_text = pdf_to_markdown(pdf_path, pdf_subfolder)
    pdf_url = f'/pdfs/{file_id}/{original_name}'

    md_filename = os.path.splitext(original_name)[0] + '.md'
    md_path = os.path.join(pdf_subfolder, md_filename)
    with open(md_path, 'w', encoding='utf-8') as md_file:
        md_file.write(markdown_text)

    md_url = f'/pdfs/{file_id}/{md_filename}'


def on_upload(e: UploadEventArguments):
    global uploaded_file
    if e.name.endswith('.pdf'):
        uploaded_file = e.content.read()
        upload_button.enable()
        ui.notify(f'File "{e.name}" uploaded successfully.', type='success')
        print(f"Uploaded file size: {len(uploaded_file)} bytes")
    else:
        ui.notify('Only .pdf files are allowed', type='warning')
        upload_button.disable()
        print(f"Rejected file upload: {e.name}")


def on_click_upload():
    global uploaded_file
    if not uploaded_file:
        ui.notify('Please upload a PDF file first.', type='warning')
        return

    try:
        convert_and_display_pdf(uploaded_file, 'uploaded.pdf')
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


# --- UI ---
with ui.card().classes('w-full max-w-3xl'):
    ui.label('Upload a PDF file')

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
