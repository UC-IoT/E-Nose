import argparse
import threading
import webbrowser
from dash import Dash, dcc, html, Input, Output

import write
import read
import realtime

def nav():
    return html.Div(
        [
            html.A("Home", href="/", style={"marginRight": "20px"}),
            html.A("Write Data", href="/write", style={"marginRight": "20px"}),
            html.A("Read / Plot", href="/read", style={"marginRight": "20px"}),
            html.A("Live Data", href="/live"),
        ],
        style={"padding": "10px 20px", "background": "#f0f0f0"},
    )

def home():
    return html.Div(
        [
            nav(),
            html.H2("eNose Dashboard", style={"textAlign": "center", "marginTop": "40px"}),
            html.Div(
                [
                    html.A("→ Go to Write Data", href="/write",
                           style={"marginRight": "40px", "fontSize": "20px"}),
                    html.A("→ Go to Read / Plot", href="/read", style={"marginRight": "40px", "fontSize": "20px"}),
                    html.A("→ Go to Live Data", href="/live", style={"fontSize": "20px"}),
                ],
                style={"textAlign": "center", "marginTop": "60px"},
            ),
        ]
    )

def create_app():
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.title = "eNose Dashboard"

    app.layout = html.Div([dcc.Location(id="url"), html.Div(id="page")])

    @app.callback(Output("page", "children"), Input("url", "pathname"))
    def display_page(pathname):
        if pathname == "/write":
            return write.layout(nav)
        elif pathname == "/read":
            return read.layout(nav)
        elif pathname == "/live":
            return realtime.layout(nav)
        return home()

    write.register_callbacks(app)
    read.register_callbacks(app)
    realtime.register_callbacks(app)

    app.validation_layout = html.Div([
        dcc.Location(id="url"),
        write.layout(nav),
        read.layout(nav),
        realtime.layout(nav),
        home(),
    ])
    return app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()

    def open_browser():
        webbrowser.open("http://127.0.0.1:8050")

    threading.Timer(1.0, open_browser).start()
    app.run(debug=args.debug, port=8050)
