import plotly.graph_objects as go

fig = go.Figure()
fig.add_trace(go.Scatter(x=[1, 2, 3], y=[4, 5, 6]))
fig.update_layout(title="Sample Plot")
fig.show()
