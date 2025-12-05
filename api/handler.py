from http.server import SimpleHTTPRequestHandler

import api.post.server.create

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if (
            self.path in ["/", "/api.js"]
            or self.path.startswith("/assets/")
            or self.path.startswith("/js/")
        ):

            if self.path == "/":
                self.path = '/index.html'
                # self.cookies_initial_set()

            return super().do_GET()

        elif self.path == "/cookies/initial/set":
            self.cookies_initial_set()
            return

        else:
            return self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path == "/api/post/server/create":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            response = api.get.server.create.create_server(post_data)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        else:
            return self.send_error(404, "Not Found")