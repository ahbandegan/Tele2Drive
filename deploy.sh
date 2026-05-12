#!/bin/bash

# Telegram FPS Bot Deployment Script
# This script helps deploy the bot to various platforms

set -e

echo "🚀 Telegram FPS Bot Deployment Script"
echo "====================================="

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found!"
    echo "Please copy env.example to .env and configure your settings:"
    echo "cp env.example .env"
    echo "Then edit .env with your bot token and other settings."
    exit 1
fi

# Load environment variables
source .env

# Check if BOT_TOKEN is set
if [ -z "$BOT_TOKEN" ]; then
    echo "❌ BOT_TOKEN not set in .env file!"
    exit 1
fi

echo "✅ Environment configuration loaded"

# Function to deploy to Heroku
deploy_heroku() {
    echo "📦 Deploying to Heroku..."
    
    # Check if Heroku CLI is installed
    if ! command -v heroku &> /dev/null; then
        echo "❌ Heroku CLI not found. Please install it first:"
        echo "https://devcenter.heroku.com/articles/heroku-cli"
        exit 1
    fi
    
    # Login to Heroku
    heroku login
    
    # Create app if it doesn't exist
    if [ -z "$HEROKU_APP_NAME" ]; then
        echo "Enter your Heroku app name:"
        read HEROKU_APP_NAME
    fi
    
    # Create or link to existing app
    heroku apps:create $HEROKU_APP_NAME 2>/dev/null || heroku git:remote -a $HEROKU_APP_NAME
    
    # Set environment variables
    heroku config:set BOT_TOKEN="$BOT_TOKEN" -a $HEROKU_APP_NAME
    heroku config:set FLASK_SECRET_KEY="$(openssl rand -base64 32)" -a $HEROKU_APP_NAME
    heroku config:set LOG_LEVEL="$LOG_LEVEL" -a $HEROKU_APP_NAME
    heroku config:set REDIRECT_URI="https://$HEROKU_APP_NAME.herokuapp.com/callback" -a $HEROKU_APP_NAME
    heroku config:set WEB_URL="https://$HEROKU_APP_NAME.herokuapp.com" -a $HEROKU_APP_NAME
    
    # Deploy
    git add .
    git commit -m "Deploy to Heroku" || true
    git push heroku main
    
    echo "✅ Deployed to Heroku!"
    echo "🌐 Your bot is available at: https://$HEROKU_APP_NAME.herokuapp.com"
}

# Function to deploy with Docker
deploy_docker() {
    echo "🐳 Building Docker image..."
    
    # Build the image
    docker build -t telegram-fps-bot .
    
    echo "✅ Docker image built successfully!"
    echo "To run the container:"
    echo "docker run -p 8080:8080 --env-file .env telegram-fps-bot"
    echo ""
    echo "Or use docker-compose:"
    echo "docker-compose up -d"
}

# Function to deploy to VPS
deploy_vps() {
    echo "🖥️  VPS Deployment Instructions"
    echo "==============================="
    echo ""
    echo "1. Upload your code to your VPS"
    echo "2. Install Docker and Docker Compose:"
    echo "   curl -fsSL https://get.docker.com -o get-docker.sh"
    echo "   sh get-docker.sh"
    echo "   sudo usermod -aG docker $USER"
    echo ""
    echo "3. Copy your .env file to the server"
    echo "4. Run: docker-compose up -d"
    echo ""
    echo "5. Set up a reverse proxy (nginx) if needed"
    echo "6. Configure your domain and SSL certificates"
}

# Main menu
echo ""
echo "Select deployment method:"
echo "1) Heroku"
echo "2) Docker (local)"
echo "3) VPS Instructions"
echo "4) Exit"
echo ""
read -p "Enter your choice (1-4): " choice

case $choice in
    1)
        deploy_heroku
        ;;
    2)
        deploy_docker
        ;;
    3)
        deploy_vps
        ;;
    4)
        echo "👋 Goodbye!"
        exit 0
        ;;
    *)
        echo "❌ Invalid choice!"
        exit 1
        ;;
esac
