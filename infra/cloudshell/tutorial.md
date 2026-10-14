# Deploy garmin-mcp to Google Cloud

This sets up the MCP server (Garmin + TrainingPeaks) on a small always-free VM.
Each step has a button that runs it in the terminal below.

## 1. Create the VM, IP and secrets

Creates the service account, encrypted secrets, static IP, firewall rules and an e2-micro VM,
then gives the server a free `sslip.io` hostname. Takes a few minutes.

```sh
bash infra/cloudshell/1-setup.sh
```

## 2. Connect GitHub sign-in

Create a GitHub OAuth App with the Homepage and callback URLs printed by step 1
(github.com → Settings → Developer settings → OAuth Apps → New OAuth App),
generate a client secret, then run this and paste the client ID and secret when asked.

```sh
bash infra/cloudshell/2-github.sh
```

## 3. Deploy

Uploads the code, installs everything on the VM and starts the server with HTTPS.

```sh
bash infra/cloudshell/3-deploy.sh
```

## 4. Log in to Garmin and TrainingPeaks

One-time logins on the VM. Garmin asks for your email, password and MFA code; TrainingPeaks
asks for your `Production_tpAuth` browser cookie (see the README). Nothing is echoed or stored
in plain text.

```sh
bash infra/cloudshell/4-logins.sh
```

## Later: reconnect TrainingPeaks

When the TrainingPeaks cookie expires (every few weeks), re-run only that login:

```sh
bash infra/cloudshell/5-trainingpeaks.sh
```

## Done

Add the connector in claude.ai: Settings → Connectors → Add custom connector, with the
`https://<host>/mcp` URL printed by step 3.
