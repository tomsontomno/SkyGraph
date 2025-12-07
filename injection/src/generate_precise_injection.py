import webbrowser
from datetime import datetime, timedelta


def build_outbound_key_string(flight_code, departure_airport, departure_date, departure_time,
                              arrival_airport, arrival_date, arrival_time) -> str:
    return (
        f"{flight_code}+"
        f"{departure_airport}%23{departure_date}T{departure_time}%7E"
        f"{arrival_airport}%23{arrival_date}T{arrival_time}"
    )


def inject_outbound_key(outbound_key):
    js_template = f"""fetch('https://multipass.wizzair.com/de/w6/subscriptions/d50b03eb-2498-49b7-a850-6124365cc048/confirmation', {{
    method: 'POST',
    headers: {{
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'content-type': 'application/x-www-form-urlencoded',
        'dnt': '1',
        'origin': 'https://multipass.wizzair.com',
        'pragma': 'no-cache',
        'priority': 'u=0, i',
        'referer': 'https://multipass.wizzair.com/de/w6/subscriptions/availability/d50b03eb-2498-49b7-a850-6124365cc048',
        'sec-ch-ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
    }},
    body: 'outboundKey={outbound_key}',
}})
.then(response => response.text())
.then(html => {{
    console.log(html);
    document.open();
    document.write(html);
    document.close();
}})
.catch(err => console.error(err));"""
    return js_template


def open_wizzair_booking_page():
    print("🛫 Enter departure and arrival airport codes:")
    dep = input("Departure airport (e.g. FCO): ").upper()
    arr = input("Arrival airport (e.g. TLV): ").upper()

    # Offer 4 date options
    today = datetime.now()
    date_options = [(today + timedelta(days=i)) for i in range(4)]
    print("\n📅 Choose your flight date:")
    for idx, date in enumerate(date_options, 1):
        print(f"{idx}. {date.strftime('%d.%m.%Y')}")

    selection = int(input("\nEnter number (1-4): "))
    chosen_date = date_options[selection - 1]
    departure_date_str = chosen_date.strftime("%Y%m%d")
    readable_date = chosen_date.strftime("%Y-%m-%d")

    # Open the booking page
    url = f"https://wizzair.com/en-gb/booking/select-flight/{dep}/{arr}/{readable_date}/null/1/0/0/null"
    print(f"\n🌍 Opening Wizz Air page: {url}")
    webbrowser.open(url)

    print(f"""
────────────────────────────────────────────────────────────────────
✅ INSTRUCTIONS:
1. In the opened browser tab, select your desired flight FIRST.
2. In the top left corner, you will see:
   - 📅 Date (e.g. "Apr 22")
   - ⏱ Time (e.g. "18:55 - 01:10")
   - 🔢 Flight code (e.g. "W6 7908")
3. Enter those values into the next prompt.

🧠 TIP: Zoom out to 75% (Ctrl + -) for better visibility.
────────────────────────────────────────────────────────────────────
""")

    return dep, arr, departure_date_str


def input_build_body_string():
    dep_airport, arr_airport, departure_date = open_wizzair_booking_page()

    print("\nPlease enter the following flight information:")

    flight_code = input("Flight code (e.g., W43386): ").replace(" ", "").replace("(", "").replace(")", "").upper()
    departure_time_str = input("Departure time (HH:MM): ").replace(":", "")
    arrival_time_str = input("Arrival time (HH:MM): ").replace(":", "")

    dep_hour = int(departure_time_str[:2])
    arr_hour = int(arrival_time_str[:2])

    # Infer arrival date based on time delta
    if arr_hour < dep_hour and dep_hour - arr_hour > 2:
        arrival_date = (datetime.strptime(departure_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    else:
        arrival_date = departure_date

    # Generate outboundKey and JS
    outbound_key = build_outbound_key_string(
        flight_code,
        dep_airport,
        departure_date,
        departure_time_str,
        arr_airport,
        arrival_date,
        arrival_time_str
    )

    js = inject_outbound_key(outbound_key)

    print("\nInject this into the /confirmation page:\n")
    print(js)


if __name__ == '__main__':
    input_build_body_string()
