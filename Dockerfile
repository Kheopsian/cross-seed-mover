# Utiliser une image Python légère comme base
FROM python:3.11-slim

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Copier le fichier des dépendances Python et les installer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier l'application (un seul fichier .py maintenant)
COPY app.py .

# Commande pour lancer l'application au démarrage du conteneur
CMD ["python3", "app.py"]