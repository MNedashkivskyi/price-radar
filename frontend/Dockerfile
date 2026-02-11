FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy application code
COPY . .

# Expose port
EXPOSE 3000

RUN npm run build

# Default command (can be overridden in docker-compose)
CMD ["npm", "run", "dev"]
