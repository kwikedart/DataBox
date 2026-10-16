#!/bin/sh
# Create the private bucket and the small VM in project sanctum-493410.
# Run this in Cloud Shell while signed in as the account that was granted access.
# This does not enable APIs, change IAM or billing, open database ports, or make objects public.
# If a command says an API must be enabled, stop and ask the project owner.
set -eu

project=sanctum-493410
bucket="${DATABOX_GCS_BUCKET:-sanctum-vm433848-data}"
zone=asia-south1-a
instance=sanctum-vm

printf '%s\n' "$bucket" | grep -Eq '^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$' || {
  echo "Bucket name must be lowercase and cannot be a URL." >&2
  exit 1
}

gcloud config set project "$project"

if gcloud storage buckets describe "gs://${bucket}" --project="$project" >/dev/null 2>&1; then
  echo "Bucket gs://${bucket} already exists."
else
  gcloud storage buckets create "gs://${bucket}" \
    --project="$project" \
    --location=asia-south1 \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

gcloud storage buckets update "gs://${bucket}" \
  --project="$project" \
  --uniform-bucket-level-access \
  --public-access-prevention

if gcloud compute instances describe "$instance" --zone="$zone" --project="$project" >/dev/null 2>&1; then
  echo "Instance ${instance} already exists. Leaving it unchanged."
else
  gcloud compute instances create "$instance" \
    --project="$project" \
    --zone="$zone" \
    --machine-type=e2-micro \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=10GB \
    --boot-disk-type=pd-standard \
    --scopes=https://www.googleapis.com/auth/devstorage.read_write,https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write \
    --tags=http-server,https-server
fi

echo "Bucket gs://${bucket} blocks public access. The VM allows HTTP and HTTPS only."
echo "Sign-in stays in DataBox. Add Firebase to this same project in the Firebase console, then add one Web app."
echo "On the VM, after Docker is installed and a domain points at it:"
echo "  DATABOX_DOMAIN=your.domain DATABOX_GCS_BUCKET=${bucket} sh deploy/prepare-env.sh"
echo "Stop the VM when you are finished:"
echo "  gcloud compute instances stop ${instance} --zone=${zone} --project=${project}"
