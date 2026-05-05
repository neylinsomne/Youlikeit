# YouLikeIt landing site — static HTML served by nginx alpine
# Lightweight (~25 MB), no build step.

FROM nginx:1.27-alpine

# Drop the default config and use ours
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf

# Copy the static site
COPY public/ /usr/share/nginx/html/

# Permissions
RUN chown -R nginx:nginx /usr/share/nginx/html

# Health check
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz || exit 1

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
