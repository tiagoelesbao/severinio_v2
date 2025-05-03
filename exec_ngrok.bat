@echo off
cd /d "C:\caminho\onde\esta\ngrok"
start "" ngrok.exe http --subdomain=imperio 5000
