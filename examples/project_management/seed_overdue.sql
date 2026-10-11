-- Optional additional sample data used by Docker Compose, separate from test fixtures.
INSERT INTO tasks (title, project_id, creator_id, assignee_id, created_at, due_date)
VALUES ('Overdue sample', 1, 1, 1, CURRENT_DATE - 10, CURRENT_DATE - 2);
