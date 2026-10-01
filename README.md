# Partner Portal

A robust Django-based partner portal for managing leads, orders, commissions, support tickets, and announcements.

## Features
- **Role-based Access Control**: Distinct features for Partners and Staff/Admin users.
- **Lead & Order Tracking**: Seamless management from prospect to converted order.
- **Support Ticketing**: Built-in support ticketing system.
- **Dashboard & Analytics**: Aggregate tracking of orders and leads with Chart.js visualizations.
- **Secure Architecture**: Environment variables for sensitive configuration, strict POST-only deletions.

## Local Setup

1. **Clone the repository** and navigate to the project directory:
   ```bash
   git clone <repo-url>
   cd "Partner portal"
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Mac/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

5. **Create a superuser**:
   ```bash
   python manage.py createsuperuser
   ```

6. **Start the development server**:
   ```bash
   python manage.py runserver
   ```
   Navigate to `http://localhost:8000/`.

## Deployment (Render)

This project is configured to be deployed on [Render.com](https://render.com/).

### Required Environment Variables
You must set the following environment variables in your Render Web Service dashboard:
- `SECRET_KEY`: A strong, random 50-character string.
- `DATABASE_URL`: Your Render PostgreSQL internal database URL.
- `RENDER`: Set to `true` (Render adds this automatically).
- `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`: Used by the `build.sh` script to automatically create the master admin user on deployment.
- `ALLOWED_HOSTS`: (Optional) Additional hosts to allow, comma-separated.

### Important Deployment Notes

- **Ephemeral File System**: On Render's free tier, the file system is ephemeral. Any files uploaded to `media/` (like portal Documents) will be lost every time the app restarts or redeploys. For production usage, it is highly recommended to configure an external storage backend like **Amazon S3** or **Cloudinary** using `django-storages`.
- **Instance Sleeping**: On Render's free tier, the instance will spin down after 15 minutes of inactivity. The first request after a period of inactivity may take 30-60 seconds as the instance spins back up.

### Management Commands

- **Recycle Bin Cleanup**: Deleted items are soft-deleted and moved to the Recycle Bin. To permanently delete items older than N days (default is 30 days), run the following command:
  ```bash
  python manage.py purge_recycle_bin --days 30
  ```
  On Render, you can schedule this as a Background Cron Job to automatically clean up old data.
