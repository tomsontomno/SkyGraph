To get a ghost flight, you first go to the confirmation page where you have to put in your credit card, while intercepting the "confirmation" package. It should have this element:
body: 'outboundKey=W61618+ABZ%2320250125T1545%7EGDN%2320250125T1855'

Then you go to wizzair.com, and check the flightnumber for your flight for example W42993, then you swap that with the dummy flight code in the body so you get:
body: 'outboundKey=W42993+ABZ%2320250125T1545%7EGDN%2320250125T1855'

After this you put in the Airport iata codes of your departure and arrival airports and update the date also. For this, its important to keep the layout of the outboundKey in mind:

# [FlightCode]+[DepartureAirport]%23[DepartureDateTime]%7E[ArrivalAirport]%23[ArrivalDateTime]

body: 'outboundKey=W42993+ABZ%2320250125T1545%7EGDN%2320250125T1855' turns into:
body: 'outboundKey=W42993+Vie%2320250127T1245%7EDXB%2320250127T2145',
for a flight from Vienna to Dubai on the 27.01.2025, that departs at 12.45 local time in Vienna and arrives 21.45 local time in Dubai

