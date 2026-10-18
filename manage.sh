#!/bin/bash

# Project Configuration
VENV_DIR="venv"
DEPENDENCY_FILES=("requirements.toml" "dependencies.toml" "environment.toml" "pyproject.toml")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' 

print_error() {
    echo -e "${RED}❌ Error: $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}🔨 $1${NC}"
}

run_command() {
    if ! "$@"; then
        print_error "Command failed: $*"
        exit 1
    fi
}

find_dependency_file() {
    for file in "${DEPENDENCY_FILES[@]}"; do
        if [[ -f "$file" ]]; then
            echo "$file"
            return 0
        fi
    done
    return 1
}

activate_venv() {
    print_info "Activating virtual environment..."
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        activate_script="$VENV_DIR/Scripts/activate"
        activate_cmd="call $activate_script"
    else
        activate_script="$VENV_DIR/bin/activate"
        activate_cmd="source $activate_script"
    fi
    
    echo "   Run this command: $activate_cmd"
    echo
}

create_venv() {
    if [[ ! -d "$VENV_DIR" ]]; then
        print_info "Creating virtual environment with uv..."
        run_command uv venv "$VENV_DIR"
    else
        print_success "Virtual environment already exists at $VENV_DIR"
    fi
}

install_dependencies() {
    local dep_file
    dep_file=$(find_dependency_file)
    
    if [[ -z "$dep_file" ]]; then
        print_warning "No dependency TOML file found. Looking for: ${DEPENDENCY_FILES[*]}"
        return
    fi

    print_info "Installing dependencies from $dep_file with uv..."
    run_command uv pip install -r "$dep_file"
}

get_venv_python() {
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        echo "$VENV_DIR/Scripts/python"
    else
        echo "$VENV_DIR/bin/python"
    fi
}

install_uvicorn() {
    print_warning "Uvicorn not found. Installing now with uv..."
    run_command uv pip install uvicorn
}

run_fastapi() {
    local venv_python
    venv_python=$(get_venv_python)
    
    # Check if uvicorn is installed in the virtual environment
    if ! "$venv_python" -m uvicorn --version &>/dev/null; then
        install_uvicorn
    fi

    print_info "Starting FastAPI server..."
    run_command "$venv_python" -m uvicorn app.main:app --reload --port 8023
}

setup() {
    create_venv
    install_dependencies
    activate_venv
}

run() {
    if [[ ! -d "$VENV_DIR" ]]; then
        print_error "Virtual environment not found. Run 'setup' first."
        exit 1
    fi
    run_fastapi
}

main() {
    local command=$1

    case "$command" in
        "setup")
            setup
            ;;
        "run")
            run
            ;;
        *)
            echo "Usage: $0 {setup|run}"
            echo "  setup - Create venv and install deps"
            echo "  run   - Start FastAPI server"
            exit 1
            ;;
    esac
}

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    print_error "uv is not installed. Please install uv first."
    exit 1
fi

# Run main function with provided arguments
main "$@"