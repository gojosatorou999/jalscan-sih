"""
FloodGAN - Generative Adversarial Network for Flood Visualization
==================================================================
A pix2pix-based conditional GAN that generates realistic flood imagery
from satellite images and flood masks.

Architecture: U-Net Generator + PatchGAN Discriminator

Author: JalScan Team

Note: PyTorch is optional - the simple_flood_overlay function works without it.
"""

from typing import Tuple, Optional
import logging
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Try to import torch - it's optional for demo mode
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available - only simple flood overlay will work")
    torch = None


def create_simple_flood_overlay(
    satellite_image: np.ndarray,
    flood_mask: np.ndarray,
    flood_color: Tuple[int, int, int] = (65, 105, 225),  # Royal blue
    opacity: float = 0.5
) -> np.ndarray:
    """
    Create a simple flood overlay without using the GAN.
    Useful for demo mode or when the model is not trained.
    
    Args:
        satellite_image: RGB satellite image [H, W, 3]
        flood_mask: Binary flood mask [H, W]
        flood_color: RGB color for flood overlay
        opacity: Opacity of the flood overlay
    
    Returns:
        Image with flood overlay [H, W, 3]
    """
    # Ensure same size
    if satellite_image.shape[:2] != flood_mask.shape:
        mask_img = Image.fromarray((flood_mask * 255).astype(np.uint8))
        mask_img = mask_img.resize((satellite_image.shape[1], satellite_image.shape[0]), Image.NEAREST)
        flood_mask = np.array(mask_img) / 255.0
    
    # Create flood overlay
    overlay = satellite_image.copy().astype(np.float32)
    
    # Apply blue tint with water texture
    for c in range(3):
        overlay[:, :, c] = np.where(
            flood_mask > 0.5,
            satellite_image[:, :, c] * (1 - opacity) + flood_color[c] * opacity,
            satellite_image[:, :, c]
        )
    
    # Add some texture variation for realism
    noise = np.random.randn(*flood_mask.shape) * 10
    for c in range(3):
        overlay[:, :, c] = np.where(
            flood_mask > 0.5,
            np.clip(overlay[:, :, c] + noise, 0, 255),
            overlay[:, :, c]
        )
    
    return overlay.astype(np.uint8)


# ============================================================================
# PyTorch-dependent classes (only available when torch is installed)
# ============================================================================

if TORCH_AVAILABLE:
    
    class UNetDownBlock(nn.Module):
        """
        Downsampling block for U-Net encoder.
        Conv -> BatchNorm -> LeakyReLU
        """
        
        def __init__(
            self,
            in_channels: int,
            out_channels: int,
            normalize: bool = True,
            dropout: float = 0.0
        ):
            super().__init__()
            
            layers = [
                nn.Conv2d(in_channels, out_channels, kernel_size=4, stride=2, padding=1, bias=False)
            ]
            
            if normalize:
                layers.append(nn.BatchNorm2d(out_channels))
            
            layers.append(nn.LeakyReLU(0.2, inplace=True))
            
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            
            self.block = nn.Sequential(*layers)
        
        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.block(x)


    class UNetUpBlock(nn.Module):
        """
        Upsampling block for U-Net decoder.
        ConvTranspose -> BatchNorm -> ReLU -> (Dropout)
        Includes skip connection from encoder.
        """
        
        def __init__(
            self,
            in_channels: int,
            out_channels: int,
            dropout: float = 0.0
        ):
            super().__init__()
            
            layers = [
                nn.ConvTranspose2d(in_channels, out_channels, kernel_size=4, stride=2, padding=1, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=True)
            ]
            
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            
            self.block = nn.Sequential(*layers)
        
        def forward(self, x: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
            x = self.block(x)
            # Concatenate with skip connection
            x = torch.cat([x, skip], dim=1)
            return x


    class FloodGenerator(nn.Module):
        """
        U-Net Generator for flood image synthesis.
        
        Input: Satellite image (3 channels) + Flood mask (1 channel) = 4 channels
        Output: Flooded satellite image (3 channels)
        """
        
        def __init__(self, in_channels: int = 4, out_channels: int = 3, features: int = 64):
            super().__init__()
            
            # Encoder (Downsampling)
            self.down1 = UNetDownBlock(in_channels, features, normalize=False)
            self.down2 = UNetDownBlock(features, features * 2)
            self.down3 = UNetDownBlock(features * 2, features * 4)
            self.down4 = UNetDownBlock(features * 4, features * 8)
            self.down5 = UNetDownBlock(features * 8, features * 8)
            self.down6 = UNetDownBlock(features * 8, features * 8)
            self.down7 = UNetDownBlock(features * 8, features * 8)
            self.down8 = UNetDownBlock(features * 8, features * 8, normalize=False)
            
            # Decoder (Upsampling with skip connections)
            self.up1 = UNetUpBlock(features * 8, features * 8, dropout=0.5)
            self.up2 = UNetUpBlock(features * 16, features * 8, dropout=0.5)
            self.up3 = UNetUpBlock(features * 16, features * 8, dropout=0.5)
            self.up4 = UNetUpBlock(features * 16, features * 8)
            self.up5 = UNetUpBlock(features * 16, features * 4)
            self.up6 = UNetUpBlock(features * 8, features * 2)
            self.up7 = UNetUpBlock(features * 4, features)
            
            # Final layer
            self.final = nn.Sequential(
                nn.ConvTranspose2d(features * 2, out_channels, kernel_size=4, stride=2, padding=1),
                nn.Tanh()
            )
        
        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # Encoder
            d1 = self.down1(x)
            d2 = self.down2(d1)
            d3 = self.down3(d2)
            d4 = self.down4(d3)
            d5 = self.down5(d4)
            d6 = self.down6(d5)
            d7 = self.down7(d6)
            d8 = self.down8(d7)
            
            # Decoder with skip connections
            u1 = self.up1(d8, d7)
            u2 = self.up2(u1, d6)
            u3 = self.up3(u2, d5)
            u4 = self.up4(u3, d4)
            u5 = self.up5(u4, d3)
            u6 = self.up6(u5, d2)
            u7 = self.up7(u6, d1)
            
            return self.final(u7)


    class PatchDiscriminator(nn.Module):
        """
        PatchGAN Discriminator.
        Classifies each NxN patch of the image as real/fake.
        """
        
        def __init__(self, in_channels: int = 6, features: int = 64):
            super().__init__()
            
            self.model = nn.Sequential(
                nn.Conv2d(in_channels, features, kernel_size=4, stride=2, padding=1),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(features, features * 2, kernel_size=4, stride=2, padding=1, bias=False),
                nn.BatchNorm2d(features * 2),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(features * 2, features * 4, kernel_size=4, stride=2, padding=1, bias=False),
                nn.BatchNorm2d(features * 4),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(features * 4, features * 8, kernel_size=4, stride=1, padding=1, bias=False),
                nn.BatchNorm2d(features * 8),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(features * 8, 1, kernel_size=4, stride=1, padding=1)
            )
        
        def forward(self, x: torch.Tensor, condition: torch.Tensor) -> torch.Tensor:
            combined = torch.cat([x, condition], dim=1)
            return self.model(combined)


    class FloodGAN(nn.Module):
        """
        Complete FloodGAN model for flood image synthesis.
        Combines U-Net Generator and PatchGAN Discriminator in pix2pix-style architecture.
        """
        
        def __init__(
            self,
            generator_features: int = 64,
            discriminator_features: int = 64,
            lambda_l1: float = 100.0
        ):
            super().__init__()
            
            self.generator = FloodGenerator(in_channels=4, out_channels=3, features=generator_features)
            self.discriminator = PatchDiscriminator(in_channels=6, features=discriminator_features)
            self.lambda_l1 = lambda_l1
            
            self.apply(self._init_weights)
            logger.info("FloodGAN initialized with pix2pix architecture")
        
        def _init_weights(self, m):
            if isinstance(m, (nn.Conv2d, nn.ConvTranspose2d)):
                nn.init.normal_(m.weight, 0.0, 0.02)
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.normal_(m.weight, 1.0, 0.02)
                nn.init.constant_(m.bias, 0)
        
        def generate(self, satellite_image: torch.Tensor, flood_mask: torch.Tensor) -> torch.Tensor:
            x = torch.cat([satellite_image, flood_mask], dim=1)
            return self.generator(x)
        
        def discriminate(self, flooded_image: torch.Tensor, satellite_image: torch.Tensor) -> torch.Tensor:
            return self.discriminator(flooded_image, satellite_image)
        
        def forward(self, satellite_image: torch.Tensor, flood_mask: torch.Tensor) -> torch.Tensor:
            return self.generate(satellite_image, flood_mask)


    class FloodVisualizerInference:
        """
        Inference wrapper for FloodGAN.
        Handles model loading, preprocessing, and postprocessing.
        """
        
        def __init__(self, model_path: Optional[str] = None, device: str = 'cpu'):
            self.device = torch.device(device)
            self.model = FloodGAN()
            self.model.to(self.device)
            self.model.eval()
            
            if model_path:
                self.load_weights(model_path)
            
            logger.info(f"FloodVisualizerInference initialized on {device}")
        
        def load_weights(self, path: str):
            checkpoint = torch.load(path, map_location=self.device)
            self.model.load_state_dict(checkpoint['generator_state_dict'])
            logger.info(f"Loaded model weights from {path}")
        
        def preprocess_image(self, image: np.ndarray) -> torch.Tensor:
            if isinstance(image, np.ndarray):
                image = Image.fromarray(image)
            image = image.resize((256, 256), Image.BILINEAR)
            image = np.array(image).astype(np.float32)
            image = (image / 127.5) - 1.0
            image = np.transpose(image, (2, 0, 1))
            return torch.from_numpy(image).unsqueeze(0).to(self.device)
        
        def preprocess_mask(self, mask: np.ndarray) -> torch.Tensor:
            if isinstance(mask, np.ndarray):
                mask = Image.fromarray((mask * 255).astype(np.uint8))
            mask = mask.resize((256, 256), Image.NEAREST)
            mask = np.array(mask).astype(np.float32) / 255.0
            mask = mask[np.newaxis, np.newaxis, :, :]
            return torch.from_numpy(mask).to(self.device)
        
        def postprocess_image(self, tensor: torch.Tensor) -> np.ndarray:
            image = tensor.squeeze(0).cpu().detach().numpy()
            image = np.transpose(image, (1, 2, 0))
            image = ((image + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
            return image
        
        @torch.no_grad()
        def synthesize_flood(self, satellite_image: np.ndarray, flood_mask: np.ndarray) -> np.ndarray:
            sat_tensor = self.preprocess_image(satellite_image)
            mask_tensor = self.preprocess_mask(flood_mask)
            output = self.model.generate(sat_tensor, mask_tensor)
            return self.postprocess_image(output)


# Example usage
if __name__ == "__main__" and TORCH_AVAILABLE:
    model = FloodGAN()
    print(f"Generator parameters: {sum(p.numel() for p in model.generator.parameters()):,}")
    print(f"Discriminator parameters: {sum(p.numel() for p in model.discriminator.parameters()):,}")
    
    batch_size = 1
    satellite = torch.randn(batch_size, 3, 256, 256)
    mask = torch.rand(batch_size, 1, 256, 256)
    
    output = model(satellite, mask)
    print(f"Input shape: satellite={satellite.shape}, mask={mask.shape}")
    print(f"Output shape: {output.shape}")
