import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
from datetime import datetime
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image

# Set page configuration
st.set_page_config(
    page_title="Texas Ethics PDF Extractor (OCR Supported)",
    page_icon="📄",
    layout="wide"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 2rem;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #374151;
        margin-bottom: 1rem;
    }
    .success-box {
        background-color: #D1FAE5;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 5px solid #10B981;
        margin: 1rem 0;
    }
    .info-box {
        background-color: #DBEAFE;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 5px solid #3B82F6;
        margin: 1rem 0;
        color: black;
    }
    .stButton>button {
        background-color: #3B82F6;
        color: white;
        font-weight: bold;
        border: none;
        padding: 0.5rem 2rem;
        border-radius: 0.5rem;
    }
    .stButton>button:hover {
        background-color: #2563EB;
    }
    </style>
""", unsafe_allow_html=True)

# Define footer patterns that should never be captured as data
FOOTER_PATTERNS = [
    "provided by Texas Ethics Commission",
    "www.ethics.state.tx.us",
    "Version V1.1",
    "Forms provided by",
    "Texas Ethics Commission"
]

# Define header patterns that should be skipped
HEADER_PATTERNS = [
    "Full name of contributor",
    "out-of-state PAC",
    "ID#:_________________________",
    "Amount of Contribution ($)",
    "Date",
    "Contributor address",
    "Principal occupation",
    "Job title",
    "See Instructions",
    "Employer",
    "SCHEDULE",
    "MONETARY POLITICAL CONTRIBUTIONS"
]

def is_footer_text(text):
    """Check if text contains footer patterns"""
    if not text:
        return False
    text_lower = text.lower()
    for pattern in FOOTER_PATTERNS:
        if pattern.lower() in text_lower:
            return True
    return False

def is_header_text(text):
    """Check if text contains header patterns"""
    if not text:
        return False
    for pattern in HEADER_PATTERNS:
        if pattern in text:
            return True
    return False

def should_skip_line(text):
    """Determine if a line should be skipped when looking for occupation/employer"""
    if not text or text.strip() == "":
        return True
    if is_footer_text(text):
        return True
    if is_header_text(text):
        return True
    if re.match(r'^\d+\.\d+$', text):  # Page numbers like "1.0"
        return True
    if re.match(r'^Sch:.*Rpt:', text):  # "Sch: 1/5 Rpt: 4/23"
        return True
    if re.match(r'^\d+ of \d+$', text):  # "3 of 23"
        return True
    
    # Additional checks for address-like patterns
    # Check for street address patterns
    if re.match(r'^\d+\s+[A-Za-z]', text):  # "123 Main St" or similar
        return True
    if re.match(r'^[A-Za-z\s]+,\s*[A-Z]{2}$', text):  # "City, ST" without zip
        return True
    if re.match(r'^[A-Z]{2}\s+\d{5}', text):  # "TX 77027" or similar
        return True
    
    return False

def get_text_from_page(page, pdf_bytes, page_num):
    """
    Try to extract text normally. If empty, perform OCR.
    """
    # 1. Try native extraction (fast, accurate for digital PDFs)
    try:
        text = page.extract_text()
    except:
        text = ""
    
    # 2. If text is found and looks substantial, return it
    if text and len(text.strip()) > 50:
        return text

    # 3. Fallback: OCR (Scanned PDF)
    # Note: This requires Tesseract and Poppler installed on the system
    try:
        # Convert specific page to image (page_num is 0-indexed, pdf2image uses 1-indexed)
        images = convert_from_bytes(
            pdf_bytes, 
            first_page=page_num+1, 
            last_page=page_num+1,
            dpi=300
        )
        
        if images:
            # Use Tesseract to get text
            # --psm 6 assumes a single uniform block of text
            ocr_text = pytesseract.image_to_string(images[0], config='--psm 6') 
            return ocr_text
    except Exception as e:
        # If OCR fails (usually missing dependencies), return empty string so the loop continues
        print(f"OCR Failed for page {page_num}: {e}")
        return ""
    
    return ""

def extract_schedule_a1_from_pdf(pdf_file):
    """Extract Schedule A1 data from uploaded PDF (Digital or Scanned)"""
    all_contributions = []
    
    try:
        # Get raw bytes for OCR usage
        pdf_bytes = pdf_file.getvalue()
        
        # Open PDF with pdfplumber using BytesIO
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total_pages = len(pdf.pages)
            
            # Progress bar setup
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for page_num in range(total_pages):
                # Update progress
                status_text.text(f"Processing page {page_num + 1} of {total_pages}...")
                progress_bar.progress((page_num + 1) / total_pages)
                
                page = pdf.pages[page_num]
                
                # Intelligent Extraction (Native or OCR)
                text = get_text_from_page(page, pdf_bytes, page_num)
                
                if not text:
                    continue

                # Check if this page is relevant
                if "MONETARY POLITICAL CONTRIBUTIONS" in text or "Schedule A1" in text:
                    
                    # Split into lines and clean
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    
                    i = 0
                    while i < len(lines):
                        line = lines[i]
                        
                        # Regex to find the start of a contribution
                        # Looks for Date, Name, and Amount on one line
                        # Modified to make $ optional (\$) for OCR robustness
                        date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s+(.+?)\s+\$?([\d,]+\.\d{2})', line)
                        
                        if date_match:
                            date = date_match.group(1)
                            name_and_maybe_more = date_match.group(2)
                            amount = f"${date_match.group(3)}" # standardize currency
                            
                            # Clean name
                            name = name_and_maybe_more
                            name = re.sub(r'\(ID#:.*?\)', '', name).strip()
                            
                            # Initialize variables
                            address = "No Data"
                            city = "No Data"
                            state = "No Data"
                            zipcode = "No Data"
                            occupation = "No Data"
                            employer = "No Data"
                            
                            # MODIFIED: Look for address in next 5 lines, handling multi-line addresses
                            address_lines = []
                            max_address_lines = 5  # Maximum lines to check for address
                            
                            for j in range(1, max_address_lines + 1):
                                if i + j >= len(lines):
                                    break
                                    
                                test_line = lines[i + j]
                                
                                # Skip empty lines
                                if not test_line.strip():
                                    if address_lines:  # If we already have address lines, stop
                                        break
                                    else:
                                        continue
                                
                                # Check for address patterns
                                is_address_line = False
                                
                                # Pattern 1: Complete address with city, state, zip
                                if ',' in test_line and re.search(r'[A-Z]{2}\s+\d', test_line):
                                    is_address_line = True
                                
                                # Pattern 2: Street address (starts with number)
                                elif re.match(r'^\d+\s+[A-Za-z]', test_line):
                                    is_address_line = True
                                
                                # Pattern 3: City, State (without zip)
                                elif re.match(r'^[A-Za-z\s]+,\s*[A-Z]{2}$', test_line):
                                    is_address_line = True
                                
                                # Pattern 4: Just state and zip
                                elif re.match(r'^[A-Z]{2}\s+\d{5}', test_line):
                                    is_address_line = True
                                
                                if is_address_line:
                                    address_lines.append(test_line)
                                elif address_lines:
                                    # If we already started collecting address lines and this doesn't look like address, stop
                                    break
                            
                            # Combine address lines
                            if address_lines:
                                address = " ".join(address_lines).strip()
                                
                                # Try to parse the complete address
                                # Look for city, state, zip pattern in the combined address
                                addr_match = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)', address)
                                if addr_match:
                                    city = addr_match.group(1).strip()
                                    state = addr_match.group(2).strip()
                                    zipcode = addr_match.group(3).strip()
                                else:
                                    # If no match, try to extract what we can
                                    addr_parts = address.split(',')
                                    if len(addr_parts) >= 2:
                                        city = addr_parts[0].strip()
                                        state_zip = addr_parts[1].strip()
                                        sz_parts = state_zip.split()
                                        if len(sz_parts) >= 2:
                                            state = sz_parts[0]
                                            zipcode = sz_parts[1]
                            
                            # MODIFIED: Skip address lines when searching for occupation/employer
                            address_line_count = len(address_lines)
                            search_start = i + address_line_count + 1
                            search_end = min(i + 15, len(lines))
                            
                            # Look for next contribution to know where to stop
                            next_contribution_idx = -1
                            for j in range(search_start, min(i + 20, len(lines))):
                                if re.search(r'\d{2}/\d{2}/\d{4}\s+.*?\d+\.\d{2}', lines[j]):
                                    next_contribution_idx = j
                                    search_end = min(search_end, next_contribution_idx)
                                    break
                            
                            # Gather potential occupation/employer lines (skip address lines)
                            potential_data_lines = []
                            for j in range(search_start, search_end):
                                test_line = lines[j]
                                
                                # Use helper to skip headers, footers
                                if should_skip_line(test_line):
                                    continue
                                
                                # Skip if this line was part of address
                                if address_lines and test_line in address_lines:
                                    continue
                                
                                # Skip lines that look like dates/amounts
                                if re.search(r'\d{2}/\d{2}/\d{4}', test_line) and re.search(r'\d+\.\d{2}', test_line):
                                    continue
                                
                                # Skip lines that look like addresses
                                if ',' in test_line and re.search(r'[A-Z]{2}\s+\d', test_line):
                                    continue
                                
                                potential_data_lines.append(test_line)
                            
                            # Logic to assign occupation/employer from found lines
                            if potential_data_lines:
                                if len(potential_data_lines) == 1:
                                    data_line = potential_data_lines[0]
                                    if ' ' in data_line:
                                        parts = data_line.split(maxsplit=1)
                                        if len(parts) == 2:
                                            occupation = parts[0]
                                            employer = parts[1]
                                    else:
                                        occupation = data_line
                                elif len(potential_data_lines) >= 2:
                                    occupation = potential_data_lines[0]
                                    employer = potential_data_lines[1]
                            
                            # Final cleanup
                            for pattern in HEADER_PATTERNS:
                                if occupation: 
                                    occupation = occupation.replace(pattern, "").strip()
                                if employer: 
                                    employer = employer.replace(pattern, "").strip()
                            
                            if occupation in ["()", "(", ")", "No Data"]: 
                                occupation = "No Data"
                            if employer in ["()", "(", ")", "No Data"]: 
                                employer = "No Data"
                            if not occupation: 
                                occupation = "No Data"
                            if not employer: 
                                employer = "No Data"
                            
                            all_contributions.append({
                                'Date': date,
                                'Contributor Name': name,
                                # 'Address': address,
                                'City': city,
                                'State': state,
                                'Zip': zipcode,
                                'Amount': amount,
                                'Occupation': occupation,
                                'Employer': employer,
                                'Page': page_num + 1
                            })
                            
                            # Skip ahead - include address lines in skip count
                            skip_amount = max(1, address_line_count + 1)
                            
                            # Try to find the next date line to skip accurately
                            for j in range(i + skip_amount, min(i + 10, len(lines))):
                                if re.search(r'\d{2}/\d{2}/\d{4}\s+.*?\d+\.\d{2}', lines[j]):
                                    skip_amount = j - i
                                    break
                            
                            i += skip_amount
                        else:
                            i += 1
            
            # Clear progress bar
            status_text.empty()
            progress_bar.empty()

        # Remove duplicates
        unique_contributions = []
        seen = set()
        for contrib in all_contributions:
            key = (contrib['Date'], contrib['Contributor Name'], contrib['Amount'])
            if key not in seen:
                seen.add(key)
                unique_contributions.append(contrib)
        
        return unique_contributions, None
        
    except Exception as e:
        return None, f"Error processing PDF: {str(e)}"

def main():
    # Header
    st.markdown('<h1 class="main-header">📄 Texas Ethics PDF Extractor</h1>', unsafe_allow_html=True)
    
    # Description
    st.markdown("""
    <div class="info-box">
    <strong>ℹ️ About this tool:</strong> This application extracts Schedule A1 (Monetary Political Contributions) 
    data from Texas Ethics Commission PDF files (Digital and Scanned/OCR) and exports it to Excel.
    </div>
    """, unsafe_allow_html=True)
    
    # File upload section
    st.markdown('<h3 class="sub-header">📤 Upload PDF File</h3>', unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf", label_visibility="collapsed")
    
    if uploaded_file is not None:
        # Show file info
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**File:** {uploaded_file.name}")
        with col2:
            st.info(f"**Size:** {uploaded_file.size / 1024:.2f} KB")
        
        # Process button
        if st.button("🚀 Extract Data", type="primary"):
            with st.spinner("Processing PDF... This may take a while if OCR is needed."):
                # Extract data
                contributions, error = extract_schedule_a1_from_pdf(uploaded_file)
                
                if error:
                    st.error(f"❌ {error}")
                    st.warning("Ensure Poppler and Tesseract-OCR are installed on the system.")
                elif not contributions:
                    st.warning("⚠️ No Schedule A1 data found in the uploaded PDF.")
                else:
                    # Create DataFrame
                    df = pd.DataFrame(contributions)
                    
                    # Sort by date and page
                    df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%Y', errors='coerce')
                    df = df.sort_values(['Date', 'Page'])
                    df = df.drop('Page', axis=1)
                    
                    # Display success message
                    st.markdown(f"""
                    <div class="success-box">
                    <strong>✅ Success!</strong> Extracted <strong>{len(df)} contributions</strong> from the PDF.
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Display preview
                    st.markdown('<h3 class="sub-header">📋 Data Preview</h3>', unsafe_allow_html=True)
                    st.dataframe(df.head(10), use_container_width=True)
                    
                    # Calculate total
                    total = 0
                    for amt in df['Amount']:
                        clean_amt = str(amt).replace('$', '').replace(',', '')
                        try:
                            total += float(clean_amt)
                        except:
                            pass
                    
                    # Display stats
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Contributions", len(df))
                    with col2:
                        st.metric("Total Amount", f"${total:,.2f}")
                    with col3:
                        if not df.empty and df['Date'].notnull().any():
                            date_range = f"{df['Date'].min().strftime('%m/%d/%Y')} to {df['Date'].max().strftime('%m/%d/%Y')}"
                        else:
                            date_range = "N/A"
                        st.metric("Date Range", date_range)
                    
                    # Prepare Excel file for download
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False, sheet_name='Schedule_A1')
                    
                    output.seek(0)
                    
                    # Download button
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"Schedule_A1_Data_{timestamp}.xlsx"
                    
                    st.download_button(
                        label="📥 Download Excel File",
                        data=output,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                    # Also show CSV option
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Download CSV File",
                        data=csv,
                        file_name=f"Schedule_A1_Data_{timestamp}.csv",
                        mime="text/csv"
                    )
    
    # Instructions sidebar
    with st.sidebar:
        st.markdown("## 📖 Instructions")
        st.markdown("""
        1. **Upload** a Texas Ethics Commission PDF
        2. **Click** the 'Extract Data' button
        3. **Preview** the extracted data
        4. **Download** as Excel or CSV
        
        ---
        **ℹ️ Scanned PDF Support:**
        If the PDF is an image (scanned), the app will use OCR. 
        This is slower than standard extraction.
        
        **Note:** Requires Tesseract and Poppler installed on the host machine.
        """)
        
        # Add a reset button
        # if st.button("🔄 Clear & Upload New"):
        #     st.rerun()

if __name__ == "__main__":
    main()