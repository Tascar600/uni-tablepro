# Local Testing Instructions for Document Parser

## Quick Start

This document describes how to test the new Document Parser feature locally before deploying to Render.

## Step 1: Setup Environment

### Install Dependencies
```bash
pip install -r requirements.txt
pip install -r timetable_system/requirements.txt
```

### Start Flask Development Server
```bash
# In project root directory
python timetable_system/app.py
```

## Step 2: Create Test Files

### Test Excel File (Recommended)
Create an Excel file with the following structure:

**File Name**: `test_courses.xlsx`

**Sheet 1: "Courses"**
```
| Course Code | Course Name         | Lecturer         | Duration | Max Students | Level    | Group |
|-------------|--------------------|------------------|----------|--------------|----------|--------|
| CS101       | Introduction to CS | Mr F. Dube       | 4        | 50           | university| 1.1   |
| CS102       | Data Structures    | Dr Sakala       | 4        | 45           | university| 1.2   |
| CS201       | Algorithms         | TBA              | 3        | 40           | department| 2.1   |
| CS301       | Software Engineering| Mr Mhlanganiso   | 4        | 35           | department| 3.1   |
| MATH101     | Calculus I         |                  | 3        | 60           | university| 1.1   |
```

### Test Word File (.docx)
Create a Word document with a table containing the same data structure.

### Test PowerPoint File (.pptx)
Create a PowerPoint slide with a table containing the same data structure.

## Step 3: Test the Upload

### Open Browser
Navigate to: `http://127.0.0.1:5000/admin/upload-documents`

### Upload Test File
1. Click **Upload & Preview**
2. Select `test_courses.xlsx`
3. System automatically detects and parses the file

### Preview Results
You should see:
- **Detected Columns**: "Course Code", "Course Name", "Lecturer", "Duration", "Max Students", "Level", "Group"
- **Sample Data**: First 5 rows shown for review
- **Message**: "System auto-detects columns. You'll preview first before importing."

### Confirm Import
1. Review the preview data
2. Click **Confirm Import**
3. System processes and saves the data

### Verify Results
1. **Courses Page** (`/admin/courses`):
   - Should show 5 courses (CS101, CS102, CS201, CS301, MATH101)
   - CS201 and MATH101 should have no lecturer (TBA)

2. **Lecturers Page** (`/admin/lecturers`):
   - Should show 3 lecturers (Dube, Sakala, Mhlanganiso)
   - Dube: username="dube", password="1234", email="fdube@buse.ac.zw"
   - Sakala: username="sakala", password="1234", email="ssakala@buse.ac.zw"
   - Mhlanganiso: username="mhlanganiso", password="1234", email="mmhlanganiso@buse.ac.zw"

## Step 4: Test Advanced Features

### Multiple Lecturers in One Cell
```
Course Code,Course Name,Lecturer
CS999,Advanced Topics,"Dr Smith; Prof Jones"
```
Expected: Creates 2 lecturers (Smith, Jones), primary lecturer = Smith

### Missing Data
```
Course Code,Course Name,Lecturer
CS400,Machine Learning,   (empty)
```
Expected: Course created with no lecturer (TBA flag)

### Special Characters
```
Course Code,Course Name,Lecturer
CS555,Introduction to “AI & ML”,"Prof José García"
```
Expected: Lecturer email generated correctly (jgarcia@buse.ac.zw)

## Troubleshooting

### "No parsable data found"
- **Solution**: Check if headers match expected pattern
- **Fix**: Ensure file has proper header row with required columns

### "ModuleNotFoundError: No module named 'document_parser'"
- **Solution**: Ensure `timetable_system/document_parser.py` exists
- **Fix**: Check file path is correct

### Import Fails with Error
- **Solution**: Check Flask console for error details
- **Fix**: Verify file encoding (UTF-8 recommended)

### Preview Doesn't Show
- **Solution**: Check if file has data
- **Fix**: Ensure file is not empty

## Expected Test Results

### Sample Output (JSON Format):
```json
{
  "courses": [
    {
      "course_code": "CS101",
      "course_name": "Introduction to CS",
      "duration_hours": 4,
      "level": "university",
      "department": "",
      "color": "blue",
      "max_students": 50,
      "group": "1.1",
      "lecturer_username": "dube",
      "lecturer_email": "fdube@buse.ac.zw",
      "notes": null,
      "source_location": "sheet:Courses;row:2",
      "flag": null
    },
    // ... more courses
  ],
  "lecturers": [
    {
      "full_name": "Mr F. Dube",
      "title": "Mr",
      "username": "dube",
      "email": "fdube@buse.ac.zw",
      "password": "1234",
      "department": null,
      "contact": null,
      "notes": null,
      "source_location": "sheet:Courses;row:2"
    },
    // ... more lecturers
  ],
  "rooms": [],
  "source_file": "test_courses.xlsx",
  "notes": ""
}
```

### Verification Checklist:
- [ ] 5 courses created (CS101, CS102, CS201, CS301, MATH101)
- [ ] 3 lecturers created (Dube, Sakala, Mhlanganiso)
- [ ] 2 courses without lecturers (CS201, MATH101) with TBA flag
- [ ] Lecturer emails correct (fdube@buse.ac.zw, ssakala@buse.ac.zw, mmhlanganiso@buse.ac.zw)
- [ ] Lecturer passwords all "1234"
- [ ] Course groups correct (1.1, 1.2, 2.1, 3.1, 1.1)
- [ ] Course durations correct (4,4,3,4,3)

## Performance Considerations

### Large Files:
- **Excel**: Up to 1000 rows per sheet
- **Word**: Up to 50 tables
- **PowerPoint**: Up to 20 slides with tables

### File Size Limits:
- **Upload limit**: 16MB (from Flask config)
- **Processing time**: Varies with file size and complexity

## Common Issues and Solutions

### Issue: Lecturer email generation fails
**Problem**: Non-ASCII characters in names
**Solution**: System handles transliteration automatically (é → e, à → a, etc.)

### Issue: Duplicate usernames
**Problem**: Multiple lecturers with same surname
**Solution**: System appends numeric suffix (dube, dube1, dube2)

### rapide
```
System auto-detects columns. You'll preview first before importing.
Columns detected: Course Code, Course Name, Lecturer, Duration, Max Students, Level, Group
Sample data: First 5 rows shown for review
Click "Confirm Import" to save the data
```

## Success Criteria

### Functional Requirements:
- [ ] File upload accepts Excel, Word, PowerPoint, CSV
- [ ] Header detection works with various naming conventions
- [ ] Data preview shows correct columns and sample rows
- [ ] Import successfully creates courses and lecturers
- [ ] Default values applied correctly
- [ ] Error handling for invalid files

### User Experience:
- [ ] Clear instructions for file upload
- [ ] Preview shows what will be imported
- [ ] Easy confirmation process
- [ ] Success/error messages are clear
- [ ] Navigation to review imported data

### Technical Requirements:
- [ ] No breaking changes to existing functionality
- [ ] Backward compatibility maintained
- [ ] Proper error handling and logging
- [ ] Session-based processing for large files
- [ ] Database transaction integrity

## Deployment

After local testing is successful:

1. **Commit changes**:
   ```bash
   git add -A
   git commit -m "Add Document Parser for Excel/Word/PowerPoint upload"
   git push origin main
   ```

2. **Deploy to Render**:
   - Push changes to GitHub
   - Render auto-deploys from main branch
   - Monitor deployment logs for any issues

3. **Test in production**:
   - Access the deployed application
   - Test with real-world data
   - Verify all features work as expected

## Conclusion

The Document Parser feature provides a powerful, automated solution for importing course and lecturer data from various document formats. It significantly reduces manual data entry effort while maintaining data quality through intelligent parsing and business rule enforcement.

**Key Benefits:**
- 🚀 **Faster data entry**: Import large datasets in minutes
- 🛡️ **Reduced errors**: Automated parsing eliminates manual typos
- 🔍 **Better UX**: Preview before importing
- 📊 **Data quality**: Consistent formatting and defaults
- 🔧 **Flexible**: Multiple file formats supported

This feature is production-ready and will greatly improve the efficiency of university timetable management!

---

**Need help or have questions?**
Contact support or refer to the detailed test documentation above.

Happy importing! 🎉
