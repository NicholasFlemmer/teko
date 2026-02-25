FROM nginx:alpine
COPY dist/ /usr/share/nginx/html/
# SPA fallback - serve index.html for all routes
RUN echo 'server { listen 8080; root /usr/share/nginx/html; location / { try_files $uri $uri/ /index.html; } }' > /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
