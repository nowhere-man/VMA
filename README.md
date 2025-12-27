# VMA - Video Metrics Analyzer

A video quality analysis tool for comparing video encoders using quality metrics and performance benchmarks.

## Features

- **Quality Metrics**: PSNR, SSIM, VMAF, VMAF-NEG per-frame and summary analysis
- **BD-Rate Calculation**: Bjontegaard Delta Rate/Metrics for encoder comparison
- **Performance Benchmarks**: Encoding FPS, CPU utilization tracking with real-time sampling
- **Template System**: Create reusable encoding templates for A/B testing
- **Interactive Reports**: Streamlit-anchord visualization with RD curves, bitrate charts, and CPU usage graphs
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
- Reports: `http://localhost:8079`
- API Docs: `http://localhost:8080/api/docs`

## Docker Deployment

### Build Image

```bash
# Build and export image
./docker/build.sh

# This generates vma-latest.tar.gz
```

### Deploy to Server

```bash
# Transfer to server
scp vma-latest.tar.gz user@server:/path/to/

# On server: use deploy script
./docker/deploy.sh vma-latest.tar.gz

# Or manually:
docker load < vma-latest.tar.gz
mkdir -p /data/vma/jobs /data/vma/templates
docker run -d \
  --name vma \
  --restart unless-stopped \
  -p 8080:8080 \
  -p 8079:8079 \
  -v /data/vma/jobs:/data/jobs \
  -v /data/vma/templates:/data/templates \
  vma:latest
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VMA_JOBS_ROOT_DIR` | /data/jobs | Job data directory |
| `VMA_TEMPLATES_ROOT_DIR` | /data/templates | Templates directory |
| `VMA_FFMPEG_PATH` | (empty) | Custom FFmpeg bin directory |
| `VMA_FFMPEG_TIMEOUT` | 600 | FFmpeg command timeout (seconds) |
| `VMA_LOG_LEVEL` | ERROR | Log level (DEBUG/INFO/WARNING/ERROR) |

### Container Management

```bash
# View logs
docker logs -f vma

# Restart
docker restart vma

# Stop and remove
docker rm -f vma
```

## Project Structure

```
VMR/
├── src/
│   ├── api/          # FastAPI endpoints
│   ├── services/     # Core business logic
│   ├── pages/        # Streamlit report pages
│   ├── templates/    # Jinja2 HTML templates
│   └── utils/        # Utility modules
├── docker/           # Docker build files
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
