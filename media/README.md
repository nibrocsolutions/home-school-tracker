# Media Library

Drop lesson attachment files here (MP3s, PDFs, images, videos, worksheets, etc.).
Teachers can pick these files from the **Edit Lesson Plan** page using **Choose media**.

## How to add files (recommended)

### Docker / Raspberry Pi

1. On the host machine, put files into the project `media/` folder (same folder as `docker-compose.yml`):

```bash
cd /path/to/home-school-tracker
mkdir -p media
cp -R ~/Downloads/the-story-of-civilization-vol4-united-states-audiobook-(1of3) media/
```

2. Confirm Docker mounts this folder (already configured in `docker-compose.yml` as `./media:/app/media`).

3. Restart is usually **not** required — new files appear immediately in the chooser.
   If files do not show up, restart the app container:

```bash
docker compose restart app
```

4. Open **Admin → Media Library** to verify the files are listed, or open a lesson plan and click **Choose media**.

### Without Docker

Set `MEDIA_ROOT` to any folder you control (defaults to `./media` or `/app/media`):

```bash
export MEDIA_ROOT=/home/robert/homeschool-media
mkdir -p "$MEDIA_ROOT"
cp -R ~/Downloads/the-story-of-civilization-vol4-united-states-audiobook-\(1of3\) "$MEDIA_ROOT/"
```

## Tips

- Keep related files in subfolders (for example `media/story-of-civilization-vol4/`).
- Supported examples: `.mp3`, `.m4a`, `.wav`, `.pdf`, `.png`, `.jpg`, `.mp4`, and most other common file types.
- Do not commit large audio files to git — this folder is ignored except for this README.
- Students open attached media from their daily checklist (MP3s play in-browser).
