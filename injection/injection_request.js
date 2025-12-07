fetch('https://multipass.wizzair.com/de/w6/subscriptions/d50b03eb-2498-49b7-a850-6124365cc048/confirmation', {
    method: 'POST',
    headers: {
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
    },
    body: 'outboundKey=5W7087+AUH%2320250312T1405%7ENQZ%2320250312T1945',
})
.then(response => response.text())
.then(html => {
    console.log(html);
    document.open();
    document.write(html);
    document.close();
})
.catch(err => console.error(err));
