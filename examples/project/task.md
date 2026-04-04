Build a REST API for task management

Create a task management API with the following:

## Data Model

- **Lists** — named containers with a position for ordering
- **Tasks** — belong to a list, have title, description, and position
- Tasks can be moved between lists and reordered within a list

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/lists | List all lists with tasks |
| POST | /api/lists | Create a list |
| PATCH | /api/lists/:id | Update list name/position |
| DELETE | /api/lists/:id | Delete list and its tasks |
| POST | /api/lists/:id/tasks | Create a task in a list |
| PATCH | /api/tasks/:id | Update task (title, description, position, list) |
| DELETE | /api/tasks/:id | Delete a task |

## Requirements

- Database models with migrations
- Input validation and error handling
- Unit tests for models and routes
- Use fractional indexing for position ordering
