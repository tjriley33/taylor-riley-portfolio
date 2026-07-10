import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email(subject, body, to_email="tjriley33@gmail.com"):
    # Load .env file if it exists
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    os.environ[key.strip()] = val.strip()

    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    try:
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
    except ValueError:
        smtp_port = 587
    smtp_user = os.environ.get("SMTP_USER", "tjriley33@gmail.com")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not smtp_password:
        print("Error: SMTP_PASSWORD is not set. Please add it to your .env file.")
        return False

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.close()
        print("Notification email sent successfully!")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

if __name__ == "__main__":
    import sys
    subject = sys.argv[1] if len(sys.argv) > 1 else "New Blog Post Posted"
    body = sys.argv[2] if len(sys.argv) > 2 else "A new article has been published on your blog."
    send_email(subject, body)
