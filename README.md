# VMA - Video Metrics Analyzer

A video quality analysis tool for comparing video encoders using quality metrics and performance benchmarks.

## Features

- **Quality Metrics**: PSNR, SSIM, VMAF, VMAF-NEG per-frame and summary analysis
- **BD-Rate Calculation**: Bjontegaard Delta Rate/Metrics for encoder comparison
- **Performance Benchmarks**: Encoding FPS, CPU utilization tracking with real-time sampling
- **Template System**: Create reusable encoding templates for A/B testing
- **Interactive Reports**: Streamlit-based visualization with RD curves, bitrate charts, and CPU usage graphs
- **REST API**: FastAPI backend for programmatic access

## Requirements

- Python 3.10+
- FFmpeg (with libvmaf support)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/nowhere-man/VMA.git
cd VMR

# Create virtual environment and install dependencies
uv venv
uv pip install -r requirements.txt

# Start the application
./run.sh
```

Access the web UI at `http://localhost:8080`

## Project Structure

```
VMR/
├── src/
│   ├── api/          # FastAPI endpoints
│   ├── services/     # Core business logic
│   ├── pages/        # Streamlit report pages
│   ├── templates/    # Jinja2 HTML templates
│   └── utils/        # Utility modules
├── jobs/             # Job output directory
└── run.sh            # Startup script
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI |
| `POST /api/templates` | Create encoding template |
| `POST /api/templates/{id}/execute` | Execute template |
| `GET /api/jobs` | List jobs |
| `GET /api/jobs/{id}` | Job details |

## License

MIT License - see [LICENSE](LICENSE) for details.
