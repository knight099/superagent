CREATE TABLE users (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE
);
CREATE TABLE projects (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    owner_id integer NOT NULL REFERENCES users(id),
    due_date date NOT NULL
);
CREATE TABLE project_members (
    project_id integer NOT NULL REFERENCES projects(id),
    user_id integer NOT NULL REFERENCES users(id),
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE tasks (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title text NOT NULL,
    project_id integer NOT NULL REFERENCES projects(id),
    creator_id integer NOT NULL REFERENCES users(id),
    assignee_id integer NOT NULL REFERENCES users(id),
    priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    done boolean NOT NULL DEFAULT false,
    created_at date NOT NULL DEFAULT CURRENT_DATE,
    due_date date NOT NULL,
    CHECK (due_date >= created_at)
);
INSERT INTO users (name) VALUES ('John'), ('Rahul'), ('Alice');
INSERT INTO projects (name, owner_id, due_date) VALUES ('Launch', 1, CURRENT_DATE + 7);
INSERT INTO project_members VALUES (1,1), (1,2);
INSERT INTO tasks (title, project_id, creator_id, assignee_id, due_date) VALUES
    ('Fix login', 1, 1, 1, CURRENT_DATE + 3),
    ('Write docs', 1, 1, 1, CURRENT_DATE + 5),
    ('Private task', 1, 3, 3, CURRENT_DATE + 4);
