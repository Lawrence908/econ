FROM nginx:alpine

ARG BUILD_TIME=unknown

# One container serves the whole tracker family; see nginx.conf for why.
# The sibling sites arrive as named build contexts (additional_contexts in
# compose.yaml), each pointing at ../<site>/src, so this image never needs
# the whole apps tree as its build context.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY tracker-locations.conf /etc/nginx/snippets/tracker-locations.conf

COPY src/ /usr/share/nginx/html/econ/
COPY --from=debt     . /usr/share/nginx/html/debt/
COPY --from=jobs     . /usr/share/nginx/html/jobs/
COPY --from=yield    . /usr/share/nginx/html/yield/
COPY --from=housing  . /usr/share/nginx/html/housing/
COPY --from=credit   . /usr/share/nginx/html/credit/
COPY --from=lending  . /usr/share/nginx/html/lending/
COPY --from=consumer . /usr/share/nginx/html/consumer/
COPY --from=output   . /usr/share/nginx/html/output/
COPY --from=freight  . /usr/share/nginx/html/freight/
COPY --from=equity   . /usr/share/nginx/html/equity/
COPY --from=diesel   . /usr/share/nginx/html/diesel/

RUN for f in /usr/share/nginx/html/*/index.html; do \
        sed -i "s|__BUILD_TIME__|${BUILD_TIME}|g" "$f"; \
    done
