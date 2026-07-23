# Home School Tracker

A self-hosted web application for managing homeschool lesson plans, daily activities, and user roles — designed to run easily on a **Raspberry Pi** via Docker.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)

## Features

- **Three user roles**, each with a dedicated home page:
  - **Admin** — system overview, metrics, user management, database backup/restore, and media library
  - **Teacher** — build daily lesson plans with activities for each student
  - **Student** — interactive checklist for today's assigned tasks
- **Media library** — drop MP3s/PDFs/other files into a shared folder and attach them to lessons
- **PostgreSQL database** in a separate container with persistent storage
- **Pre-populated demo data** — sample users and lesson plans ready on first launch
- **Professional, kid-friendly UI** — warm colors, progress tracking, and celebration banners

## Quick Start (Raspberry Pi or any Docker host)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed
- Git (to clone the repository)

### Install in two commands

```bash
git clone https://github.com/nibrocsolutions/home-school-tracker.git
cd home-school-tracker
```

Copy the example environment file and optionally customize passwords:

```bash
cp .env.example .env
```

Start the application (builds and runs both the app and database):

```bash
docker compose up -d --build
```

Open your browser to **http://localhost:8080** (or `http://<your-pi-ip>:8080` from another device on your network).

### Stop the application

```bash
docker compose down
```

To stop and remove database data as well:

```bash
docker compose down -v
```

## Demo Accounts

| Role           | Username        | Password    |
|----------------|-----------------|-------------|
| Admin          | `admin`         | `admin123`  |
| Teacher        | `teacher`       | `teacher123`|
| Student        | `student`       | `student123`|

> **Important:** Change all default passwords before exposing this app beyond your home network. Update `SECRET_KEY` and `POSTGRES_PASSWORD` in your `.env` file.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐
│   Web Browser   │────▶│  hst-app :8080   │
└─────────────────┘     │  (FastAPI)       │
                        └────────┬─────────┘
                                 │
                        ┌────────▼─────────┐
                        │  hst-db :5432    │
                        │  (PostgreSQL 16) │
                        └──────────────────┘
```

- **App container** (`hst-app`): Python FastAPI application serving HTML pages
- **DB container** (`hst-db`): PostgreSQL with a named volume (`postgres_data`) for persistence

Both containers restart automatically (`unless-stopped`) — ideal for a always-on Raspberry Pi.

## Database Backup & Restore

Admins can export and import a full JSON backup of all application data from the admin dashboard:

- **Export Backup** — downloads users, lesson plans, activities, and completion records
- **Import Backup** — restores data from a previously exported file (replaces all current data)

Use daily exports as a safety net when rebuilding the application after a failure.

## Media Library (MP3s, PDFs, and other lesson files)

Teachers can attach files from a shared media folder when editing a lesson plan (**Choose media**).

### Add files on Docker / Raspberry Pi

1. Copy files into the project `media/` folder (next to `docker-compose.yml`):

```bash
cd /path/to/home-school-tracker
mkdir -p media
cp -R ~/Downloads/the-story-of-civilization-vol4-united-states-audiobook-\(1of3\) media/
```

2. Docker Compose mounts `./media` into the app as `/app/media` (already configured).
3. Open **Admin → Media Library** to confirm the files appear, or edit a lesson and click **Choose media**.

New files usually show up immediately. If they do not:

```bash
docker compose restart app
```

### Optional configuration

| Variable     | Default                         | Description                          |
|--------------|---------------------------------|--------------------------------------|
| `MEDIA_ROOT` | `/app/media` (Docker) or `./media` | Absolute path to the media library |

Large audio files should stay in `media/` on disk — they are gitignored on purpose.

## Configuration

All settings are in `.env`:

| Variable            | Default                      | Description                          |
|---------------------|------------------------------|--------------------------------------|
| `POSTGRES_USER`     | `hst_user`                   | Database username                    |
| `POSTGRES_PASSWORD` | `change_me_secure_password`  | Database password                    |
| `POSTGRES_DB`       | `home_school_tracker`        | Database name                        |
| `SECRET_KEY`        | (see `.env.example`)         | JWT signing key for sessions         |
| `APP_PORT`          | `8080`                       | Host port mapped to the web app      |
| `MEDIA_ROOT`        | `/app/media` (Docker)        | Folder for lesson media attachments  |

## Raspberry Pi Tips

1. **ARM support**: All images (`python:3.12-slim-bookworm`, `postgres:16-alpine`) are multi-arch and work on Raspberry Pi 4/5 (64-bit OS recommended).
2. **Find your Pi's IP**: Run `hostname -I` on the Pi, then visit `http://<ip>:8080`.
3. **Auto-start on boot**: Docker's `restart: unless-stopped` policy handles this once containers are running.
4. **Low memory**: The stack is lightweight (~200–400 MB RAM total). A Pi 4 with 2 GB+ RAM is sufficient.

## Development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL separately, then set DATABASE_URL
export DATABASE_URL=postgresql://hst_user:password@localhost:5432/home_school_tracker
export SECRET_KEY=dev-secret

uvicorn app.main:app --reload --port 8000
```

## Project Structure

```
home-school-tracker/
├── app/
│   ├── main.py           # Application entry point
│   ├── models.py         # Database models
│   ├── auth.py           # Authentication & authorization
│   ├── seed.py           # Demo data seeder
│   ├── backup.py         # Database export/import
│   ├── media_library.py  # Shared lesson media folder helpers
│   ├── routers/          # Route handlers
│   ├── templates/        # HTML templates (Jinja2)
│   └── static/           # CSS & JavaScript
├── media/                # Drop MP3s/PDFs here (mounted into Docker)
├── docker-compose.yml    # Multi-container orchestration
├── Dockerfile            # App container definition
├── requirements.txt      # Python dependencies
└── .env.example          # Environment template
```

## Future Hosting

The same `docker compose up -d --build` workflow works on any cloud VM or container platform. For external hosting, ensure you:

1. Set strong values for `SECRET_KEY` and `POSTGRES_PASSWORD`
2. Place a reverse proxy (nginx, Caddy, Traefik) in front for HTTPS
3. Restrict database port exposure (only the `app` service needs to be public)

## License

Open source — use and modify freely for your homeschool needs.
