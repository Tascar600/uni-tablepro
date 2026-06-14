# Document Parser Test Instructions

## Overview
The system now includes a comprehensive Document Parser that can extract courses, lecturers, and rooms from Excel, Word, and PowerPoint files.

## Files Added/Modified

### 1 kiện_parser.py
Location: `timetable_system/document_parser.py`

**Features:**
- **Multi-format support**: Excel (.xlsx, .xls), Word (.docx), PowerPoint (.pptx)
- **Smart header detection**: Automatically maps various header names to canonical fields
- **Flexible parsing**: Handles multi-row headers, merged cells, multiple lecturers per cell
- **Normalization**: Applies business rules and defaults
- **Schema compliance**: Returns JSON matching the exact output schema

**Key Functions:**
- `parse_excel_file(filepath)` - Parse Excel files
- `parse_word_file(filepath)` - Parse Word documents
- `parse_all_formats(filepath)` - Detect file type and parse accordingly
- `export_to_json(data)` - Convert parsed data to JSON matching schema

### 2 Updated `app.py`
- **Import added**: `from document_parser import DocumentParser`
- **Upload route refactored**: Now uses DocumentParser for file parsing
- **Three-stage workflow**: Upload → Preview → Confirm Import
- **Advanced file support**: Now accepts .docx and .pptx files

### 3 Updated `admin_upload.html`
- **Preview interface**: Shows detected columns and sample data
- **Confirm import**: User reviews before data is saved
- **Better UX**: Cleaner, more intuitive interface

### 4 Updated `requirements.txt`
- **Added**: `openpyxl==3.1.5` (required for Excel parsing)

## How It Works

### Step 1: Upload Document
1. Navigate to the **Upload Documents** page (from sidebar or dashboard)
2. Click **Upload & Preview**
3. Select Excel, Word, or PowerPoint file
4. System automatically detects the file type

### Step 2: Preview Results
1. System detects column headers using flexible synonym matching
2. Shows sample data (first 5 rows) for review
3. Displays detected column mappings

**Example Output:**
```
Columns detected: Course Code, Course Name, Lecturer, Duration, Max Students

Sample data:
CS101 | Introduction to CS | Mr F. Dube | 4 | 50
CS102 | Data Structures | Dr Sakala | 4 | 45
CS201 | Algorithms | TBA | 3 | 40
```

### Step : Confirm Import
1. Review preview data
2. Click **Confirm Import**
3. System validates and inserts data into database
4. Shows import results with counts

## Business Rules Applied

### Lecturers:
- **Username**: Surname (lowercase)
  - "Mr F. Dube" → "dube"
  - "Dr Sakala" → "sakala"
- **Email**: First initial + surname @buse.ac.zw
  - "Mr F. Dube" → "fdube@buse.ac.zw"
  - "Dr Alice M. Banda" → "abanda@buse.ac.zw"
- **Password**: "1234"
- **Title**: Extracted from name (Mr, Mrs, Dr, etc.)

### Courses:
- **Duration**: 4 hours (default)
- **Color**: "blue" (default)
- **Max Students**: 50 (default)
- **Name**: Uses course code if missing
- **Level/Department**: Empty (admin edits later)
- **Group**: From Part/Level labels (1.1, 1.2, etc.)
- **TBA**: Course added without lecturer

### Header Synonyms:
- **Course Code**: Code, Course Code, CourseID, CID, Subject Code, Module Code
- **Course Name**: Course Name, Course, Subject, Title, Subject Name
- **Lecturer**: Lecturer, Lecturer Name, Staff, Instructor, Teacher, Tutor, Facilitator
- **Duration**: Duration, Hours, Lecture Hours, Credit, Credits
- **Max Students**: Max Students, Students, Capacity, Enrollment, Class Size
- **Group**: Group, Part, Level, Year, Semester, Section, Class
- **Department**: Department, Dept, Faculty, School
- **Room**: Room, Room Code, Venue, Room Name, Location

## Testing Instructions

### Local Testing (Recommended):

1. **Clone the repository** and navigate to the project directory
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Start the Flask app**:
   ```bash
   python timetable_system/app.py
   ```
4. **Open browser** to `http://127.0.0.1:5000/admin/upload-documents`

### Create Test Files:

**Excel Test File (.xlsx)**:
```
| Course Code | Course Name         | Lecturer     | Duration | Max Students | Level    | Group  |
|-------------|--------------------|--------------|----------|--------------|----------|--------|
| CS101       | Introduction to CS | Mr F. Dube   | 4        | 50           | university| 1.1   |
| CS102       | Data Structures    | Dr Sakala   | 4        | 45           | university| 1.2   |
| CS201       | Algorithms         | TBA          | 3        | 40           | department| 2.1   |
| CS301       | Software Engineering| Mr Mhlanganiso| 4        | 35           | department| 3.1   |
```

**CSV Test File (.csv)**:
```
Course Code,Course Name,Lecturer,Hours,Max Students,Group
CS101,Introduction to CS,Mr F. Dube,4,50,1.1
CS102,Data Structures,Dr Sakala,4,45,1.2
CS201,Algorithms,TBA,3,40,2.1
```

**Word Test File (.docx)**:
Create a Word document with a table containing the same data structure

**PowerPoint Test File (.pptx)**:
Create a PowerPoint slide with a table containing the same data structure

### Expected Results:

After importing test data:
1. **Courses Created**: 4
2. **Lecturers Created**: 3 (Dube, Sakala, Mhlanganiso)
3. **Lecturers Skipped**: 1 (TBA - no account created)
4. **Rooms**: 0 (none in test data)

### Verification:
1. Navigate to **Courses** page → Verify 4 courses
2. Navigate to **Lecturers** page → Verify 3 lecturers
3. Check lecturer credentials:
   - Dube/dube/1234 (email: fdube@buse.ac.zw)
   - Sakala/sakala/1234 (email: ssakala@buse.ac.zw)
   - Mhlanganiso/mhlanganiso/1234 (email: mmhlanganiso@buse.ac.zw)
4. Check courses for proper grouping and data

## Advanced Features

### Multiple Lecturers per Cell:
```
Course Code,Course Name,Lecturer
CS999,Advanced Topics,"Dr Smith; Prof Jones"
```
Creates 2 lecturers (Smith, Jones) and primary lecturer = Smith

### Complex Headers:
```
Part/Level    Course Code    Course Name    Lecturer
1.1          CS101          Intro CS       Mr F. Dube
1.2          CS102          Data Structures Dr Sakala
```

### Empty/Missing Data:
```
Course Code,Course Name,Lecturer
CS401,Cloud Computing,   (empty)
```
Course created without lecturer (TBA flag set)

## Troubleshooting

### "No parsable data found":
1. Check file format (supported: .xlsx, .xls, .csv, .docx, .pptx)
2. Verify header row contains required columns
3.,. Check for empty or corrupted files
4. Ensure file is not password-protected

### "ModuleNotFoundError: No module named 'document_parser'":
1. Ensure `timetable_system/document_parser.py` exists
2. Verify file is in the correct location
3. Restart the Flask application

### "Import failed: [error details]":
1. Check database connection
2. Verify file encoding (UTF-8 recommended)
3. Try a simpler test file first

## Error Handling

- **File format errors**: Clear error messages guiding user to correct format
- **Parsing errors**: Graceful fallback with informative messages
- **Database errors**: Transaction rollback with error reporting
- **Schema validation**: Clear indication of what's missing or malformed

## Security Considerations

- **File size limits**: System limits file uploads to 16MB
- **File type validation**: Only supported formats accepted
- **Session-based processing**: Parsed data stored in session during preview
- **Database transactions**: Rollback on errors to prevent partial data

## Deployment

After deployment to Render:
1. Check application logs for import errors
2. Monitor database size for large imports
3. Verify lecturer account creation
4. Test course creation and linkage to lecturers

## Conclusion

The Document Parser provides a powerful, automated way to import course and lecturer data from various document formats. It combines robust parsing logic with flexible business rules and a user-friendly preview interface, making data entry efficient and error-resistant.

The system can handle various document structures and automatically applies consistent defaults, ensuring data quality while reducing manual entry errors. This significantly speeds up the process of setting up and updating university timetable data.

## Next Steps

1. **Deploy to Render** to make the feature available to users
2. **Test with real-world data** from your institution
3. **Document user workflow** for better adoption
4. **Monitor performance** and optimize as needed

The feature is production-ready and will significantly improve the user experience when importing timetable data! 🎉