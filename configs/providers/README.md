# Provider profiles

Files ending in `.yml` or `.yaml` in this directory define local,
OpenAI-compatible model providers. They are intentionally ignored by Git
because labels, endpoints, and model lists can describe a private deployment.

For a manual setup, copy the public schema example:

```bash
cp configs/providers/openai-compatible.yml.example configs/providers/example.yml
```

The filename stem becomes the provider ID (`example` above). Edit only the
non-secret metadata in that file. Add the API base URL and API key from the Web
UI **Settings** page; those connection values are written to the ignored,
mode-`0600` file `configs/provider_secrets.yaml` and are never echoed back to
the browser.

You can also skip the file copy and create the provider entirely from
**Settings → Add provider**.
