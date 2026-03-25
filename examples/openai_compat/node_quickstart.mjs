const endpoint = (process.env.AMARYLLIS_ENDPOINT || "http://127.0.0.1:8000").replace(/\/+$/, "");
const token = (process.env.AMARYLLIS_TOKEN || "dev-token").trim();

const payload = {
  messages: [
    { role: "system", content: "You are concise." },
    { role: "user", content: "Give one-line hello from local API." }
  ],
  stream: false
};

const response = await fetch(`${endpoint}/v1/chat/completions`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${token}`
  },
  body: JSON.stringify(payload)
});

if (!response.ok) {
  const text = await response.text();
  throw new Error(`Request failed: ${response.status} ${text}`);
}

const data = await response.json();
const message = data?.choices?.[0]?.message?.content ?? "";
console.log(message);
