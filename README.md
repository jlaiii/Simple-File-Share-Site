# Simple File Share

A lightweight, self-hosted file sharing application built with Flask, SQLite, and a modern web frontend (Tailwind CSS). This application allows users to upload files (ZIP, RAR, 7Z up to 1GB), which are then made available via a shareable link. Files automatically expire after 3 days of inactivity (no downloads).

## Features

-   **Drag & Drop Upload:** Intuitive file upload experience.
-   **Shareable Links:** Generate unique links for each uploaded file.
-   **Temporary Downloads:** Download links are temporary and one-time use to enhance security.
-   **Automatic Expiration:** Files are automatically deleted from the server 3 days after their last download.
-   **File Type Restrictions:** Only allows `zip`, `rar`, and `7z` files.
-   **Size Limit:** Maximum file size of 1GB.
-   **Basic Statistics:** Displays active files, total storage used, and total uploads ever.
-   **Responsive Design:** Modern UI built with Tailwind CSS.

## Technologies Used

-   **Backend:** Python (Flask)
-   **Database:** SQLite3
-   **Web Server:** Waitress
-   **Frontend:** HTML, CSS (Tailwind CSS), JavaScript

## Setup and Installation

### Prerequisites

-   Python 3.x
-   `pip` (Python package installer)

### Steps

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd simple-file-share
    ```
    *(Note: Replace `<your-repo-url>` with the actual URL of your repository.)*

2.  **Install dependencies:**
    The `server.py` script will attempt to install Flask, Werkzeug, and Waitress automatically if not found. However, you can also install them manually:
    ```bash
    pip install Flask werkzeug waitress
    ```

3.  **Run the server:**
    ```bash
    python server.py
    ```
    The server will start on `http://0.0.0.0:8080` (accessible via `http://127.0.0.1:8080` from the same machine).

4.  **Access the application:**
    Open your web browser and navigate to `http://127.0.0.1:8080`.

## Project Structure

-   `server.py`: The main Flask backend application, handling file uploads, link generation, downloads, and database interactions.
-   `index.html`: The main frontend page for uploading files.
-   `download_page.html`: The dedicated page for downloading an uploaded file.
-   `uploads/`: Directory where uploaded files are stored (created automatically if it doesn't exist).
-   `file_registry.db`: SQLite database file to store file metadata and download tokens.

## How it Works

1.  **Upload:**
    -   Users visit the `index.html` page.
    -   They can drag and drop a file or click to select one.
    -   The frontend uses `XMLHttpRequest` to send the file to the `/upload` endpoint.
    -   The `server.py` saves the file with a unique ID, stores its metadata in `file_registry.db`, and generates a dedicated `page/{unique_id}` link.
    -   This `page/{unique_id}` link is returned to the frontend and displayed to the user for sharing.

2.  **Download Page:**
    -   When someone accesses the `page/{unique_id}` link, `server.py` renders `download_page.html`, injecting file details (name, size).
    -   On this page, a "Generate Download Link" button is present.

3.  **Download Link Generation:**
    -   Clicking the "Generate Download Link" button sends a POST request to `/generate_download_link/{file_id}`.
    -   The server generates a *new, unique, and temporary* download token. This token is valid for `TOKEN_EXPIRATION_MINUTES` (default 60 minutes) and is stored in the database.
    -   A direct download link (`/download/{token}`) is returned to the frontend.

4.  **File Download:**
    -   The frontend automatically redirects the user's browser to the `/download/{token}` link.
    -   The `server.py` verifies the token's validity and expiration.
    -   If valid, the server serves the actual file, updates the `last_download_timestamp` and `download_count` for the file, and *immediately deletes the used token* from the database, making the link a one-time use.
    -   If the token is invalid or expired, the download fails, and the user is prompted to generate a new link.

5.  **Cleanup:**
    -   A background thread (`cleanup_expired_items`) runs every hour.
    -   It deletes files from the `uploads/` directory and their corresponding database entries if their `last_download_timestamp` is older than `EXPIRATION_DAYS` (default 3 days).
    -   It also cleans up any expired download tokens.

## Configuration

You can modify the following variables in `server.py`:

-   `UPLOAD_FOLDER`: Directory to store uploaded files (default: `'uploads'`)
-   `DATABASE_FILE`: Name of the SQLite database file (default: `'file_registry.db'`)
-   `ALLOWED_EXTENSIONS`: Set of allowed file extensions (default: `{'zip', 'rar', '7z'}`)
-   `MAX_CONTENT_LENGTH`: Maximum allowed file size in bytes (default: `1 * 1024 * 1024 * 1024` which is 1 GB)
-   `EXPIRATION_DAYS`: Number of days after the last download before a file is deleted (default: `3`)
-   `TOKEN_EXPIRATION_MINUTES`: How long a generated download token is valid in minutes (default: `60`)
-   `HOST`: The host IP address the server listens on (default: `'0.0.0.0'`)
-   `PORT`: The port the server listens on (default: `8080`)

## Contributing

Feel free to fork the repository, make improvements, and submit pull requests!

## License

This project is open-source and available under the MIT License.

