-- Update bill_automator_family_mapping table to use line_id instead of line_name
-- Run this script in your Supabase SQL editor

-- Drop the existing family_mapping table
DROP TABLE IF EXISTS group_bill_automation.bill_automator_family_mapping;

-- Recreate the family_mapping table with line_id instead of line_name
CREATE TABLE group_bill_automation.bill_automator_family_mapping (
    id SERIAL PRIMARY KEY,
    family_id INTEGER NOT NULL,
    line_id INTEGER NOT NULL,
    FOREIGN KEY (family_id) REFERENCES group_bill_automation.bill_automator_families(id),
    FOREIGN KEY (line_id) REFERENCES group_bill_automation.bill_automator_lines(id)
);

-- Add indexes for better performance
CREATE INDEX ix_group_bill_automation_bill_automator_family_mapping_family_id 
ON group_bill_automation.bill_automator_family_mapping(family_id);

CREATE INDEX ix_group_bill_automation_bill_automator_family_mapping_line_id 
ON group_bill_automation.bill_automator_family_mapping(line_id);
