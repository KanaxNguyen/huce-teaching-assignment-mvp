-- Frozen SQLite schema at revision 0001; independent of live ORM models.
CREATE TABLE courses (
	id INTEGER NOT NULL, 
	code VARCHAR(50) NOT NULL, 
	name VARCHAR(300) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE lecturers (
	id INTEGER NOT NULL, 
	code VARCHAR(30), 
	canonical_name VARCHAR(200) NOT NULL, 
	aliases JSON NOT NULL, 
	confirmed BOOLEAN NOT NULL, 
	max_credits FLOAT NOT NULL, 
	source_file VARCHAR(300), 
	source_sheet VARCHAR(100), 
	source_row INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (code), 
	UNIQUE (canonical_name)
);

CREATE TABLE semesters (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	department_name VARCHAR(200) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	head_name VARCHAR(200) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE classes (
	id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	class_code VARCHAR(100) NOT NULL, 
	credits FLOAT NOT NULL, 
	merged_group_id VARCHAR(100), 
	merged_confirmed BOOLEAN NOT NULL, 
	locked_assignment BOOLEAN NOT NULL, 
	assigned_lecturer_id INTEGER, 
	source_file VARCHAR(300) NOT NULL, 
	source_sheet VARCHAR(100) NOT NULL, 
	source_row INTEGER NOT NULL, 
	raw_values JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (semester_id, course_id, class_code), 
	FOREIGN KEY(semester_id) REFERENCES semesters (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id), 
	FOREIGN KEY(assigned_lecturer_id) REFERENCES lecturers (id)
);

CREATE TABLE constraints (
	id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	constraint_type VARCHAR(50) NOT NULL, 
	hardness VARCHAR(10) NOT NULL, 
	weight FLOAT NOT NULL, 
	lecturer_id INTEGER, 
	target JSON NOT NULL, 
	raw_text TEXT, 
	confirmed BOOLEAN NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(semester_id) REFERENCES semesters (id), 
	FOREIGN KEY(lecturer_id) REFERENCES lecturers (id)
);

CREATE TABLE import_batches (
	id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	source_files JSON NOT NULL, 
	summary JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(semester_id) REFERENCES semesters (id)
);

CREATE TABLE optimization_runs (
	id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	score FLOAT, 
	summary JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(semester_id) REFERENCES semesters (id)
);

CREATE TABLE output_template_profiles (
	id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	source_file VARCHAR(300) NOT NULL, 
	source_sheet VARCHAR(100) NOT NULL, 
	header_row INTEGER NOT NULL, 
	mappings JSON NOT NULL, 
	missing_fields JSON NOT NULL, 
	preview JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(semester_id) REFERENCES semesters (id)
);

CREATE TABLE seminars (
	id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	chair_name VARCHAR(200) NOT NULL, 
	members JSON NOT NULL, 
	alternatives JSON NOT NULL, 
	weight FLOAT NOT NULL, 
	hardness VARCHAR(10) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(semester_id) REFERENCES semesters (id)
);

CREATE TABLE validation_issues (
	id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	code VARCHAR(60) NOT NULL, 
	message TEXT NOT NULL, 
	source_file VARCHAR(300), 
	source_sheet VARCHAR(100), 
	source_row INTEGER, 
	field VARCHAR(100), 
	raw_value TEXT, 
	suggestion TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(semester_id) REFERENCES semesters (id)
);

CREATE TABLE assignments (
	id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	run_id INTEGER NOT NULL, 
	class_id INTEGER NOT NULL, 
	lecturer_id INTEGER NOT NULL, 
	locked BOOLEAN NOT NULL, 
	penalty FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, class_id), 
	FOREIGN KEY(semester_id) REFERENCES semesters (id), 
	FOREIGN KEY(run_id) REFERENCES optimization_runs (id), 
	FOREIGN KEY(class_id) REFERENCES classes (id), 
	FOREIGN KEY(lecturer_id) REFERENCES lecturers (id)
);

CREATE TABLE sessions (
	id INTEGER NOT NULL, 
	class_id INTEGER NOT NULL, 
	weekday INTEGER NOT NULL, 
	start_period INTEGER NOT NULL, 
	end_period INTEGER NOT NULL, 
	room VARCHAR(200) NOT NULL, 
	start_date DATE, 
	end_date DATE, 
	raw_weeks VARCHAR(80) NOT NULL, 
	active_weeks JSON NOT NULL, 
	source_row INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(class_id) REFERENCES classes (id)
);

