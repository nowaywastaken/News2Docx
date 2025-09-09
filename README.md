# News2Docx

## Environment Variables

The application requires API credentials to be provided via environment variables, command line arguments, or a JSON configuration file.

- `CRAWLER_API_TOKEN` – Token for the crawler API.
- `SILICONFLOW_API_KEY` – API key for the SiliconFlow service.

Example:

```bash
export CRAWLER_API_TOKEN="your_crawler_token"
export SILICONFLOW_API_KEY="your_siliconflow_key"
```

You may also pass these values using the command line options `--api-token` and `--siliconflow-api-key` or supply a JSON config file via `--config` with fields `crawler_api_token` and `siliconflow_api_key`.
