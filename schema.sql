-- Run this in your Supabase SQL Editor ONLY IF the 'documents' table does NOT have a 'sub_section_name' column yet.

ALTER TABLE documents
ADD COLUMN sub_section_name text DEFAULT 'General Sub-Section';
