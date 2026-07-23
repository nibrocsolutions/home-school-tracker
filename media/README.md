# Media Library

Drop lesson attachment files here (MP3s, PDFs, images, videos, worksheets, etc.).
Teachers can attach them later from Edit Lesson Plan using **Add media files**, or upload new files from School Year Planning with **Add Media**.

## Recommended folder layout

```text
media/
├── history/          # audiobooks, history PDFs, etc.
├── math/
├── language-arts/
├── science/
└── other/
```

These subject folders are created automatically when the app starts.

## How to add files (recommended)

### From the web app (teachers)

1. Open **School Year Planning**.
2. Below **Progress**, click **Add Media**.
3. Choose a folder (for example `history`) and select one or more files.
4. Click **Upload**. Files are available immediately in the lesson plan media picker.

### Docker / Raspberry Pi (copy onto the server)

1. Copy files into a subject folder under project `media/`:

```bash
cd /path/to/home-school-tracker
mkdir -p media/history
cp -R ~/Downloads/the-story-of-civilization-vol4-united-states-audiobook-\(1of3\) media/history/
```

Or copy the MP3s directly into History:

```bash
mkdir -p media/history
cp -R ~/Downloads/the-story-of-civilization-vol4-united-states-audiobook-\(1of3\)/* media/history/
```

2. Docker mounts `./media` into the app as `/app/media`.
3. Open **Admin → Media Library** to verify, or edit a lesson and click **Add media files**.
4. In the chooser, pick the `history` folder chip, then select one or more files and click **Add selected**.

Restart is usually not required for new files. If they do not appear:

```bash
docker compose restart app
```

### Without Docker

```bash
export MEDIA_ROOT=/home/robert/homeschool-media
mkdir -p "$MEDIA_ROOT/history"
cp -R ~/Downloads/the-story-of-civilization-vol4-united-states-audiobook-\(1of3\) "$MEDIA_ROOT/history/"
```

## Tips

- Keep related files in subject subfolders (`media/history/...`).
- Teachers can attach multiple files to the same lesson activity.
- Supported examples: `.mp3`, `.m4a`, `.wav`, `.pdf`, `.png`, `.jpg`, `.mp4`, and most other common file types.
- Do not commit large audio files to git — this folder is ignored except for README/gitkeep files.
- Students open attached media from their daily checklist (audio plays in-browser).
