# Encryption Policy

## Data at Rest
AcmeCloud encrypts customer data at rest in production systems using AES-256. This requirement applies to production databases, object storage, and attached storage volumes that store customer data.

## Data in Transit
AcmeCloud protects customer data in transit over public networks using TLS 1.2 or higher. Insecure transport protocols are not permitted for production services that transmit customer data externally.

## Centralized Key Management
Encryption keys for production systems are managed centrally through the company's cloud key management service (KMS). Production services use KMS-managed keys for encryption operations rather than maintaining separate local key stores for customer data.

## Key Access Restrictions
Access to encryption key administration is restricted to authorized security or platform administrators. Key management permissions are limited by role and reviewed as part of privileged access controls.
