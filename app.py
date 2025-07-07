# app.py
import argparse, webbrowser
from dash import Dash, dcc, html, Input, Output
import threading
import webbrowser

import data_capture           
import read_plot


# ───────────── shared navigation bar ─────────────
def nav():
    return html.Div(
        [
            html.A("Home", href="/",          style={"marginRight": "20px"}),
            html.A("Write Data", href="/write", style={"marginRight": "20px"}),
            html.A("Read / Plot", href="/read"),
        ],
        style={"padding": "10px 20px", "background": "#f0f0f0"},
    )


# ───────────── simple home page ─────────────
def home():
    return html.Div(
        [
            nav(),
            html.H2("eNose Dashboard", style={"textAlign": "center", "marginTop": "40px"}),
            html.Div(
                [
                    html.A("→ Go to Write Data", href="/write",
                           style={"marginRight": "40px", "fontSize": "20px"}),
                    html.A("→ Go to Read / Plot", href="/read", style={"fontSize": "20px"}),
                ],
                style={"textAlign": "center", "marginTop": "60px"},
            ),
        ]
    )


# ───────────── build & wire the Dash app ─────────────
def create_app():
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.title = "eNose Dashboard"

    # basic page container
    app.layout = html.Div([dcc.Location(id="url"), html.Div(id="page")])

    # router
    @app.callback(Output("page", "children"), Input("url", "pathname"))
    def display_page(pathname):
        if pathname == "/write":
            return data_capture.layout(nav)           # page A
        elif pathname == "/read":
            return read_plot.layout(nav)              # page B
        return home()

    # register callback bundles from the two helper modules
    data_capture.register_callbacks(app)
    read_plot.register_callbacks(app)

    # make Dash happy at launch → include every component id
    app.validation_layout = html.Div(
        [
            dcc.Location(id="url"),
            data_capture.layout(nav),
            read_plot.layout(nav),
            home(),
        ]
    )
    return app


# ───────────── main ─────────────
# app.py  – entry‑point  (last lines only)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()

    # open browser in a separate thread after short delay
    def open_browser():
        webbrowser.open("http://127.0.0.1:8050")

    threading.Timer(1.0, open_browser).start()
    app.run(debug=args.debug, port=8050)

