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
cd VMA

# Create virtual environment and install dependencies
uv venv
uv pip install -r requirements.txt

# Start the application
./run.sh
```

Access the web UI at `http://localhost:8080`
- Reports: `http://localhost:8081`
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
scp vma-latest.tar.gz user@server:/path/to/

./docker/deploy.sh vma-latest.tar.gz

# Or manually:
docker load < vma-latest.tar.gz
DATA_DIR=$(cd docker && pwd)/data
mkdir -p "${DATA_DIR}/jobs" "${DATA_DIR}/templates"
docker run -d \
  --name vma \
  --restart unless-stopped \
  -p 8080:8080 \
  -p 8081:8081 \
  -v "${DATA_DIR}/jobs:/data/jobs" \
  -v "${DATA_DIR}/templates:/data/templates" \
  vma:latest
```

### Configuration

- 配置文件：`config.yml`
- 修改端口或路径时直接编辑 `config.yml`

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
VMA/
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
