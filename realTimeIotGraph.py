#region imports for plotly/dash graphing api
import dash
from dash.dependencies import Input, Output, State
import dash_core_components as dcc
import dash_html_components as html
import plotly
import plotly.graph_objs as go
import atexit
#endregion

#region general utility imports
from collections import defaultdict
from datetime import datetime, timedelta
import MySQLdb as sql
import math
import pandas as pd
import sys
#endregion

#region IP Addresses of all devices we are tracking
ip = {
    'Chromecast':       '192.168.12.77',
    'Echo Dot 2':       '192.168.12.79',
    'Echo Dot':         '192.168.12.92',
    'Eufy Genie':       '192.168.12.147',
    'Eufy Genie 2':     '192.168.12.217',
    'Fire Stick':       '192.168.12.113',
    'Google Home':      '192.168.12.48',
    'IP Camera':        '192.168.12.58',
    'Nintendo Switch':  '192.168.12.160',
    'Roku':             '192.168.12.69',
    'Samsung Hub':      '192.168.12.100',
    'Samsung TV':       '192.168.12.191',
    'Smart Light':      '192.168.12.27',
    'Xbox':             '192.168.12.251',
    'Echo Show':        '192.168.12.122',
}
#corresponding logic to extract necessary strings for dropdowm form our ip device list
dropdown_options = [{'label': device, 'value': device} for device in sorted(ip.keys())]
#endregion
with open('loginCredentials') as loginCredentials:
    credentials = loginCredentials.read().splitlines()

host = credentials[0]
user = credentials[1]
passwd = credentials[2]
db = credentials[3]

#region Currently Unused Functions
def power_query(db_connection, device, n):
    sql_query = "SELECT power_mw, time FROM ip_log.power WHERE "
    sql_query += "name='" + device + "' "
    sql_query += "ORDER BY time DESC LIMIT " + str(n)

    dataframe = pd.read_sql_query(sql_query, db_connection)

    return dataframe

def extract_time_range(dataframe):
    # I'm assuming I queried for the power with the "DESC" keyword,
    # thus latest time first, most recent time last
    start_time, end_time = dataframe['time'].iloc[-1], dataframe['time'].iloc[0]
    return start_time, end_time

def get_power_and_net_traff(devices, n):
    db_connection = connect_to_ip_log_db()
    atexit.register(db_connection.close)
    power = {}
    net_traff = {}
    for curr_device in devices:
        # Setup power table for a device
        power[curr_device] = power_query(db_connection, curr_device, n)

        # Setup network traffic information for a device
        start_time, end_time = extract_time_range(power[curr_device])
        net_traff_frame = net_traff_query(db_connection, curr_device, start_time, end_time)
        net_traff[curr_device] = extract_throughput(net_traff_frame, curr_device)

    db_connection.close()
    return power, net_traff

def net_traff_query(db_connection, device, start_time, end_time):
    start_time, end_time = str(start_time), str(end_time)
    sql_query = "SELECT time, source, destination, size FROM ip_log.ip WHERE "
    sql_query += "time BETWEEN '" + start_time + "' AND '" + end_time + "' AND "
    sql_query += "(source = '" + ip[device] + "' OR destination = '" + ip[device] + "')"

    dataframe = pd.read_sql_query(sql_query, db_connection)

    return dataframe

def extract_throughput(dataframe, device):
    throughput = defaultdict(lambda: {'in': 0, 'out': 0, 'total': 0})

    for _, packet in dataframe.iterrows():
        if packet['source'] == ip[device]:
            throughput[packet['time']]['out'] += packet['size']
        elif packet['destination'] == ip[device]:
            throughput[packet['time']]['in'] += packet['size']

        throughput[packet['time']]['total'] += packet['size']

    return pd.DataFrame.from_dict(throughput, orient='index')

def preserve_trace_visibility(prev_data, curr_data):
    hidden_traces = set()

    for trace in prev_data:
        if not trace['visible']:
            hidden_traces.add(trace['name'])

    print hidden_traces

    for trace in curr_data:
        if trace['name'] in hidden_traces:
            trace['visible'] = False

#endregion

#region Functions for main network/power graph
def power_query_in_range(db_connection, device, start_time, end_time):
    sql_query = """SELECT power_mw, time FROM ip_log.power
                   WHERE
                       name = '%s' AND
                       time BETWEEN '%s' AND '%s';
    """ % (device, start_time, end_time)

    dataframe = pd.read_sql_query(sql_query, db_connection)

    return dataframe

def throughput_query_in_range(db_connection, device, start_time, end_time):
    sql_query = """
        SELECT
            time,
            CASE WHEN type IS NULL THEN 'total' ELSE type END type,
            SUM(size) AS total_throughput
        FROM ip_log.ip
        WHERE
            time BETWEEN '%s' AND '%s' AND
            (source = '%s' OR destination = '%s')
        GROUP BY time, type WITH ROLLUP;
    """ % (start_time, end_time, ip[device], ip[device])

    dataframe = pd.read_sql_query(sql_query, db_connection)

    return dataframe

def get_power_and_net_traff_in_range(devices, start_time, end_time):
    db_connection = connect_to_ip_log_db()
    atexit.register(db_connection.close)
    power = {}
    net_traff = {}
    for curr_device in devices:
        power[curr_device] = power_query_in_range(db_connection, curr_device, start_time, end_time)

        net_traff[curr_device] = throughput_query_in_range(db_connection, curr_device, start_time, end_time)

    db_connection.close()
    return power, net_traff

def create_figure(prev_fig, devices, power, net_traff):
    #visibilities = {d['name']: d['visible'] for d in prev_fig['data']}
    #for d in prev_fig['data']:
    #    print d

    scatter_data = []
    annotations = []
    for curr_device in devices:
        powerDF = power[curr_device]
        if not powerDF.empty:
            # Append power graph
            scatter_data.append(go.Scatter(
                x = powerDF['time'],
                y = powerDF['power_mw'],
                name = curr_device + ' Power',
            #    visible=visibilities[curr_device + ' Power'] or 'legendonly'
            ))
            avgPower = powerDF['power_mw'].mean()
            startTime, endTime = powerDF['time'].iloc[0], powerDF['time'].iloc[-1]
            scatter_data.append(go.Scatter(
                x = [startTime, endTime],
                y = [avgPower] * 2,
                name = curr_device + ' Average Power',
            #    visible=visibilities[curr_device + ' Power'] or 'legendonly'
            ))

            maxPowerRow = powerDF['power_mw'].idxmax()
            minPowerRow = powerDF['power_mw'].idxmin()
            maxPower, minPower = powerDF['power_mw'].iloc[maxPowerRow], powerDF['power_mw'].iloc[minPowerRow]
            maxPowerTime, minPowerTime = powerDF['time'].iloc[maxPowerRow], powerDF['time'].iloc[minPowerRow]
            annotations += [
                dict(x=startTime, y=avgPower, text=str(avgPower)),
                dict(x=maxPowerTime, y=maxPower, text=str(maxPower)),
                dict(x=minPowerTime, y=minPower, text=str(minPower))
            ]

        # Append incoming, outgoing, and total network throughput
        #df = net_traff[curr_device]
        #for data_direction in ('incoming', 'outgoing', 'total'):
        #    dev_net_traff_in_dir = df.loc[(df['type'] == data_direction) & (df['time'].notnull())]
        #    if not dev_net_traff_in_dir.empty:
        #        scatter_data.append(go.Scatter(
        #            x = dev_net_traff_in_dir['time'],
        #            y = dev_net_traff_in_dir['total_throughput'],
        #            name = curr_device + ' ' + data_direction + ' Throughput',
        #            yaxis = 'y2',
        #        #    visible=visibilities[curr_device + ' Power'] or 'legendonly'
        #        ))
        #        #avgY = [dev_net_traff_in_dir['total_throughput'].mean()]*2
        #        #avgX = [dev_net_traff_in_dir['time'].iloc[0], dev_net_traff_in_dir['time'].iloc[-1]]
        #        #print dev_net_traff_in_dir['time'].iloc[0]
        #        #scatter_data.append(go.Scatter(
        #        #    x = avgX,
        #        #    y = avgY,
        #        #    name = curr_device + ' ' + data_direction + ' Average Throughput',
        #        #    yaxis = 'y2',
        #        ##    visible=visibilities[curr_device + ' Power'] or 'legendonly'
        #        #))

    layout = go.Layout(
        yaxis=dict(title='Power (mW)'),
        yaxis2=dict(title='Throughput (Bytes)', overlaying='y', side='right'),
        legend=dict(x=0, y=1.05, orientation='h'),
        margin=go.Margin(l=70, r=70, b=50, t=50, pad=4),
        height=800,
        annotations=annotations
    )

    return go.Figure(data=scatter_data, layout=layout)
#endregion

#region Functions for protocol bar graph
def create_protocol_bar_graph(protocol_data):
    #split into two seperate tables, one for incoming data and one for outgoing data
    directions = ('incoming', 'outgoing')
    data = []

    for direction in directions:
        protocol_data_in_direction = protocol_data.loc[protocol_data['type'] == direction]
        trace = go.Bar(
            x = protocol_data_in_direction['protocol'],
            y = protocol_data_in_direction['COUNT(protocol)'],
            name = direction + ' packets',
        )
        data.append(trace)

    layout = go.Layout(
        barmode='stack',
        legend=dict(x=0, y=1.05, orientation='h')
    )

    return go.Figure(data=data, layout=layout)

def protocol_query(db_connection, device, start_time, end_time):
    start_time, end_time = str(start_time), str(end_time)

    sql_query = "SELECT protocol, type, source, destination, COUNT(protocol) FROM ip_log.ip WHERE "
    sql_query += "time BETWEEN '" + start_time + "' AND '" + end_time + "' AND "
    sql_query += "(source = '" + ip[device] + "' OR destination = '" + ip[device] + "') "
    sql_query += "GROUP BY protocol, type "
    sql_query += "ORDER BY protocol DESC"

    dataframe = pd.read_sql_query(sql_query, db_connection)

    return dataframe

def get_protocol_stats(devices, start_time_range, end_time_range):
    db_connection = connect_to_ip_log_db()
    atexit.register(db_connection.close)
    protocol_stats = pd.DataFrame()

    for device in devices:
        device_protocol_stats = protocol_query(db_connection, device, start_time_range, end_time_range)
        device_protocol_stats['protocol'] = device_protocol_stats['protocol'] + device

        protocol_stats = protocol_stats.append(device_protocol_stats)

    db_connection.close()

    return protocol_stats.sort_values(by='protocol')

#endregion

#region utility function
def extract_time_fields(time_str):
    str_fields = time_str.split(':')

    hours, minutes, seconds = 0, 0, 0
    if len(str_fields) == 3:
        hours, minutes, seconds = map(int, time_str.split(':'))
    elif len(str_fields) == 2:
        minutes, seconds = map(int, time_str.split(':'))

    return hours, minutes, seconds

def get_time_range(use_time_range, interval, interval2, start_time_range, end_time_range):
    """
        Given user defined paramaters above, get a time range string for the SQL call BETWEEN

        Args:
            interval: interval defined for live updating graph

            interval2: interval defined for static graph

            start_time_range: start time (may or may not be defined)

            end_time_range: end time (may or may not be defined)

            returns: start_time, end_time tuple for SQL BETWEEN query

        returns: a timedate formatted string for start time and end time
    """

    if use_time_range and interval2 and (start_time_range or end_time_range):
        h, m, s = extract_time_fields(interval2)
        time_delta = timedelta(hours=h, minutes=m, seconds=s)

        # parse the time strings
        if start_time_range:
            start_time_range = start_time_range.strip()
            if '/' in start_time_range:
                start_time_range = datetime.strptime(start_time_range, "%m/%d/%Y %I:%M:%S %p")
            else:
                start_time_range = datetime.strptime(start_time_range, "%Y-%m-%d %H:%M:%S")
        elif end_time_range:
            end_time_range = end_time_range.strip()
            if '/' in end_time_range:
                end_time_range = datetime.strptime(end_time_range, "%m/%d/%Y %I:%M:%S %p")
            else:
                end_time_range = datetime.strptime(end_time_range, "%Y-%m-%d %H:%M:%S")

        # if one of the fields are missing, calculate the other time range with time delta
        if not (start_time_range and end_time_range):
            if start_time_range:
                end_time_range = start_time_range + time_delta
            elif end_time_range:
                start_time_range = end_time_range - time_delta

    elif not use_time_range:
        h, m, s = extract_time_fields(interval)

        end_time_range = datetime.now()
        start_time_range = end_time_range - timedelta(hours=h, minutes=m, seconds=s)

    return str(start_time_range), str(end_time_range)

def connect_to_ip_log_db():
    try:
        db_connection = sql.connect(host, user, passwd, db)

        db_connection.ping(True)
    except IOError:
        print "Missing 'loginCredentials' file, create one with login info"
        print "put the: host, user, password, and database"
        print "they all go on their own line with no modifiers"
    except Exception as exception:
        print exception
        sys.exit("Couldn't connect to database")

    return db_connection

#endregion

#region HTML layout for webpage
app = dash.Dash(__name__)
app.layout = html.Div([
    html.Div([
       'Interval: '
    ],
        id='interval-header',
        style={'display': 'inline-block', 'font-weight': 'bold', 'font-size': '20px', 'padding-right': '10px'}
    ),
    html.Div([
        dcc.Input(id='interval', type='text', value='00:12:00'),
    ],
        style={'display': 'inline-block'}
    ),
    html.Div([
        'Time Range: ',
    ],
        id='time-range-header',
        style={'display': 'inline-block', 'font-weight': 'bold', 'font-size': '20px', 'padding-right': '10px', 'padding-left': '30px'}
    ),
    html.Div([
        dcc.Input(id='start-time', type='text', value='2018-05-07 12:00:00', placeholder='YYYY-MM-DD HH:MM:SS'),
    ],
        style={'display': 'inline-block'}
    ),
    html.Div([
        dcc.Input(id='end-time', type='text', value='2018-05-07 12:01:00', placeholder='YYYY-MM-DD HH:MM:SS'),
    ],
        style={'display': 'inline-block'}
    ),
    html.Div([
        dcc.Input(id='interval2', type='text', value='00:12:00', placeholder='HH:MM:SS'),
    ],
        style={'display': 'inline-block'}
    ),
    html.Button(
        'Update Time Range Graphing',
        id='update-button',
        style={'display': 'inline-block'}
    ),
    html.Div([
        dcc.Checklist(
            id='use-time-range',
            options=[
                {'label': 'Use Time Range (Won\'t Update)', 'value': 'use_time_range'}
            ],
            values=[],
            labelStyle={'display': 'inline-block'}
        )
    ],
        style={'display': 'inline-block'}
    ),
    html.Div(
        children=dcc.Dropdown(
            id='device-dropdown',
            options=dropdown_options,
            multi=True,
            placeholder='Select the devices you want to display',
            value=[]
        ),
    ),
    dcc.Graph(id='live-update-graph'),
    dcc.Graph(id='protocol-graph'),
    dcc.Interval(
        id='interval-component',
        interval=1.5*1000, # in milliseconds
        n_intervals=0
    ),
])
app.css.append_css({
    'external_url': 'https://codepen.io/chriddyp/pen/bWLwgP.css'
})
#endregion

#region side callbacks for main graph
#region Grey out live update fields when not in use
@app.callback(Output('interval-header', 'style'),
              [Input('use-time-range', 'values')])
def toggle_interval_header_color(use_time_range):
    if not use_time_range:
        return {'color': 'black', 'display': 'inline-block', 'font-weight': 'bold', 'font-size': '20px', 'padding-right': '10px'}
    elif use_time_range:
        return {'color': 'grey', 'display': 'inline-block', 'font-weight': 'bold', 'font-size': '20px', 'padding-right': '10px'}
@app.callback(Output('interval', 'style'),
              [Input('use-time-range', 'values')])
def toggle_interval_color(use_time_range):
    if not use_time_range:
        return {'color': 'black', 'display': 'inline-block'}
    elif use_time_range:
        return {'color': 'grey', 'display': 'inline-block'}
#endregion

#region Grey out static fields when not in use
@app.callback(Output('time-range-header', 'style'),
              [Input('use-time-range', 'values')])
def toggle_range_header_color(use_time_range):
    if use_time_range:
        return {'color': 'black', 'display': 'inline-block', 'font-weight': 'bold', 'font-size': '20px', 'padding-right': '10px', 'padding-left': '30px'}
    elif not use_time_range:
        return {'color': 'grey', 'display': 'inline-block', 'font-weight': 'bold', 'font-size': '20px', 'padding-right': '10px', 'padding-left': '30px'}
@app.callback(Output('start-time', 'style'),
              [Input('use-time-range', 'values')])
def toggle_start_range_color(use_time_range):
    if use_time_range:
        return {'color': 'black', 'display': 'inline-block'}
    elif not use_time_range:
        return {'color': 'grey', 'display': 'inline-block'}
@app.callback(Output('end-time', 'style'),
              [Input('use-time-range', 'values')])
def toggle_end_range_color(use_time_range):
    if use_time_range:
        return {'color': 'black', 'display': 'inline-block'}
    elif not use_time_range:
        return {'color': 'grey', 'display': 'inline-block'}
@app.callback(Output('interval2', 'style'),
              [Input('use-time-range', 'values')])
def toggle_interval2_color(use_time_range):
    if use_time_range:
        return {'color': 'black', 'display': 'inline-block'}
    elif not use_time_range:
        return {'color': 'grey', 'display': 'inline-block'}
#endregion

#region Stop updating if interval is chosen
@app.callback(Output('interval-component', 'interval'),
              [Input('use-time-range', 'values')])
def toggle_interval(use_time_range):
    if use_time_range:
        return 2147483647   # 2^31 - 1 (large value to disable updates)
    elif not use_time_range:
        return 1.5 * 1000   # regular time interval (every 1.5 seconds)
#endregion
#endregion

#region Main Graphing function
@app.callback(Output('live-update-graph', 'figure'),
             [Input('device-dropdown', 'value'),
              Input('interval-component', 'n_intervals'),
              Input('use-time-range', 'values'),
              Input('update-button', 'n_clicks')],
             [State('live-update-graph', 'figure'),
              State('start-time', 'value'),
              State('end-time', 'value'),
              State('interval', 'value'),
              State('interval2', 'value')])
def update_graph_live(devices, n, use_time_range, clicks, prev_fig, start_time_range, end_time_range, interval, interval2):
    start_time_range, end_time_range = get_time_range(use_time_range, interval, interval2, start_time_range, end_time_range)

    power, net_traff = get_power_and_net_traff_in_range(devices, start_time_range, end_time_range)

    fig = create_figure(prev_fig, devices, power, net_traff)

    #if prev_fig: preserve_trace_visibility(prev_fig['data'], fig['data'])

    # Print if any of the figures are empty
    #for device in power.keys():
    #    if power[device].empty:
    #        print device + " power is empty"
    #        print power[device]
    #for device in net_traff.keys():
    #    if net_traff[device].empty:
    #        print device + " network traffic is empty"
    #        print net_traff[device]

    return fig
#endregion

#region protocol bar graph
@app.callback(Output('protocol-graph', 'figure'),
             [Input('device-dropdown', 'value'),
              Input('interval-component', 'n_intervals'),
              Input('use-time-range', 'values'),
              Input('update-button', 'n_clicks')],
             [State('live-update-graph', 'figure'),
              State('start-time', 'value'),
              State('end-time', 'value'),
              State('interval', 'value'),
              State('interval2', 'value')])
def update_protocol_graph(devices, n, use_time_range, clicks, prev_fig, start_time_range, end_time_range, interval, interval2):
    if devices:
        start_time_range, end_time_range = get_time_range(use_time_range, interval, interval2, start_time_range, end_time_range)

        protocol_stats = get_protocol_stats(devices, start_time_range, end_time_range)

        fig = create_protocol_bar_graph(protocol_stats)

        return fig
    else:
        return None
#endregion

if __name__ == '__main__':
    app.run_server(debug=True)
