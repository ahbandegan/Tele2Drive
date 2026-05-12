#!/usr/bin/env python3
"""
Setup script for WOWDrive Bot with Web Server
"""

import os
import json
import sys
from pathlib import Path


def create_directories():
    """Create necessary directories"""
    directories = ['uploads', 'logs', 'templates']
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
        print(f"✅ Created directory: {directory}")


def create_env_file():
    """Create .env file from template"""
    env_file = Path('.env')
    if not env_file.exists():
        env_content = """# Telegram Bot Configuration
BOT_TOKEN=your_telegram_bot_token_here

# Web Server Configuration
FLASK_SECRET_KEY=your_secret_key_here

# Optional: Logging level
LOG_LEVEL=INFO
"""
        with open(env_file, 'w') as f:
            f.write(env_content)
        print("✅ Created .env file")
        print("⚠️  Please edit .env file and add your BOT_TOKEN and FLASK_SECRET_KEY")
    else:
        print("✅ .env file already exists")


def create_client_secrets_template():
    """Create Google client secrets template"""
    creds_file = Path('client_secrets.json')
    if not creds_file.exists():
        template = {
            "web": {
                "client_id": "your_client_id_here",
                "project_id": "your_project_id_here",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": "your_client_secret_here",
                "redirect_uris": [
                    "http://localhost:8080/callback"
                ]
            }
        }
        with open(creds_file, 'w') as f:
            json.dump(template, f, indent=2)
        print("✅ Created client_secrets.json template")
        print("⚠️  Please replace with your actual Google Cloud credentials")
    else:
        print("✅ client_secrets.json already exists")


def create_readme():
    """Create README file with setup instructions"""
    readme_content = """# 🤖 WOWDrive Bot with Web Server

A powerful Telegram bot that uploads files directly to Google Drive with a web-based OAuth authentication system.

## ✨ Features

- 📤 **File Upload**: Upload any file from Telegram to Google Drive
- 🔄 **Chunked Upload**: Handle large files (>20MB) with progress tracking
- 📊 **Real-time Progress**: Live progress updates every 20 seconds
- 📁 **File Management**: List, rename, and delete files
- 💾 **Storage Stats**: View your Google Drive storage usage
- 🔐 **Web-based Auth**: Secure OAuth2 authentication via web interface
- ⚡ **Queue System**: Handle multiple uploads efficiently
- 🌐 **Web Interface**: Beautiful web interface for authentication

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.8 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- Google Cloud Project with Drive API enabled

### 2. Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run setup
python setup.py
```

### 3. Configuration

#### Telegram Bot Setup
1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Create a new bot with `/newbot`
3. Copy the bot token

#### Google Drive API Setup
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Google Drive API
4. Create OAuth2 credentials (Web application)
5. Add `http://localhost:8080/callback` to redirect URIs
6. Download the credentials and save as `client_secrets.json`

#### Environment Configuration
1. Edit `.env` file:
   ```
   BOT_TOKEN=your_telegram_bot_token_here
   FLASK_SECRET_KEY=your_secret_key_here
   LOG_LEVEL=INFO
   ```

2. Replace `client_secrets.json` with your Google Cloud credentials

### 4. Run the Application

```bash
python main.py
```

This will start both the web server (port 8080) and the Telegram bot.

## 📋 Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot and show welcome message |
| `/help` | Show help message and available commands |
| `/login` | Get authentication URL for Google Drive |
| `/stat` | Show your Drive storage usage |
| `/list` | List your recent files |
| `/rename <fileId> <newName>` | Rename a file in Drive |
| `/remove <fileId>` | Delete a file from Drive |
| `/privacy` | View privacy policy and terms |

## 🌐 Web Interface

The web server provides:
- **Home Page**: `http://localhost:8080/`
- **Authentication**: `http://localhost:8080/login`
- **Privacy Policy**: `http://localhost:8080/policy`
- **Terms of Service**: `http://localhost:8080/terms`

## 🔧 Project Structure

```
src/
├── main.py                 # Main entry point
├── bot.py                  # Telegram bot implementation
├── site.py                 # Web server (Flask)
├── drive.py                # Google Drive operations
├── config.py               # Configuration settings
├── setup.py                # Setup script
├── client_secrets.json     # Google OAuth credentials
├── templates/              # HTML templates
│   ├── Index.html
│   ├── googlesignIn.html
│   ├── notfound.html
│   ├── policy.html
│   └── terms.html
├── uploads/               # Temporary upload folder
└── requirements.txt       # Python dependencies
```

## 🔐 Authentication Flow

1. User sends `/login` command to bot
2. Bot provides authentication URL
3. User opens URL in browser
4. User authorizes with Google
5. Web server handles OAuth callback
6. Credentials are stored for the user
7. User can now upload files

## 📤 Upload Process

### Small Files (≤20MB)
1. Send file to bot
2. File is queued for upload
3. Direct upload to Google Drive
4. Completion notification with file ID

### Large Files (>20MB)
1. Send file to bot
2. File is queued for upload
3. Chunked upload with progress tracking
4. Progress updates every 20 seconds
5. Completion notification with file ID

## 🛠️ Development

### Running Tests
```bash
python example_usage.py
```

### Debugging
Set `LOG_LEVEL=DEBUG` in `.env` for detailed logs.

## 🚨 Troubleshooting

### Common Issues

**Bot not responding:**
- Check `BOT_TOKEN` in `.env`
- Verify bot is running
- Check logs for errors

**Authentication failed:**
- Verify `client_secrets.json` is correct
- Check Google Drive API is enabled
- Ensure redirect URI is `http://localhost:8080/callback`

**Web server not starting:**
- Check port 8080 is available
- Verify Flask is installed
- Check `FLASK_SECRET_KEY` is set

**Upload fails:**
- Check internet connection
- Verify Google Drive storage space
- Try smaller files first

## 📊 File Size Limits

| File Type | Limit | Upload Method |
|-----------|-------|---------------|
| Small files | ≤20MB | Direct upload |
| Large files | >20MB | Chunked upload |
| Maximum | 2GB | Chunked upload |

## 🔒 Security & Privacy

- **OAuth2 Authentication**: Secure Google Drive access via web
- **No Data Storage**: Files are uploaded directly to your Drive
- **Token Management**: Credentials stored per user
- **Revocable Access**: Revoke access anytime from Google Account
- **Privacy First**: No file content stored on bot server

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is open source. Please use responsibly and in accordance with Google Drive Terms of Service.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the logs
3. Contact the bot administrator

---

**Made with ❤️ for seamless file management**
"""

    with open('README.md', 'w') as f:
        f.write(readme_content)
    print("✅ Created README.md")


def main():
    """Main setup function"""
    print("🚀 Setting up WOWDrive Bot with Web Server...")
    print()

    try:
        create_directories()
        create_env_file()
        create_client_secrets_template()
        create_readme()

        print()
        print("🎉 Setup completed!")
        print()
        print("Next steps:")
        print("1. Get a bot token from @BotFather")
        print("2. Set up Google Drive API credentials (Web application)")
        print("3. Edit .env file with your bot token and secret key")
        print("4. Replace client_secrets.json with your Google credentials")
        print("5. Run: python main.py")
        print()
        print("🌐 Web server will be available at: http://localhost:8080")
        print("🤖 Bot will be available on Telegram")

    except Exception as e:
        print(f"❌ Setup failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
