import copy
import math
import json
import csv
import hashlib
import logging
import time
from typing import List, Tuple, Dict, Optional, Any
from functools import lru_cache
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import defaultdict, Counter

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration globale du système
class OrbsConfig:
    """Configuration centralisée pour le système Orbs avec cache distribué"""
    # Performance
    CACHE_SIZE = 256
    POOL_MAX_SIZE = 1000
    BOUNDING_BOX_THRESHOLD = 100
    DISTRIBUTED_CACHE_SIZE = 10000  # Cache global pour calculs lourds
    
    # Calculs
    DEFAULT_EPSILON_T = 1e-3
    DEFAULT_EPSILON_SPATIAL = 1e-6
    MAX_COMPRESSION_SYMBOLS = 10000
    
    # Validation
    MIN_RADIUS = 1e-9
    MAX_ORBITS_PER_LAYER = 50000
    
    # Export
    DEFAULT_CSV_DELIMITER = ','
    JSON_INDENT = 2
    
    # Cache distribué pour opérations coûteuses
    _distributed_cache = {}
    _cache_hits = 0
    _cache_misses = 0
    
    @classmethod
    def update(cls, **kwargs):
        """Met à jour la configuration"""
        for key, value in kwargs.items():
            if hasattr(cls, key.upper()):
                setattr(cls, key.upper(), value)
            else:
                logger.warning(f"Configuration inconnue: {key}")
    
    @classmethod
    def get_cached_result(cls, operation_key, computation_func, *args, **kwargs):
        """Cache distribué intelligent pour les opérations coûteuses"""
        args_hash = hash(str(args))
        kwargs_hash = hash(str(sorted(kwargs.items())))
        cache_key = f"{operation_key}_{args_hash}_{kwargs_hash}"
        
        if cache_key in cls._distributed_cache:
            cls._cache_hits += 1
            return cls._distributed_cache[cache_key]
        
        # Calcul et mise en cache
        result = computation_func(*args, **kwargs)
        
        # Gestion de la taille du cache
        if len(cls._distributed_cache) >= cls.DISTRIBUTED_CACHE_SIZE:
            # Suppression LRU basique (supprime 10% des entrées les plus anciennes)
            old_keys = list(cls._distributed_cache.keys())[:cls.DISTRIBUTED_CACHE_SIZE // 10]
            for key in old_keys:
                del cls._distributed_cache[key]
        
        cls._distributed_cache[cache_key] = result
        cls._cache_misses += 1
        return result
    
    @classmethod
    def get_cache_stats(cls):
        """Statistiques du cache distribué"""
        total = cls._cache_hits + cls._cache_misses
        hit_rate = cls._cache_hits / total if total > 0 else 0
        return {
            "cache_size": len(cls._distributed_cache),
            "cache_hits": cls._cache_hits,
            "cache_misses": cls._cache_misses,
            "hit_rate": round(hit_rate, 3),
            "memory_efficiency": round(len(cls._distributed_cache) / max(cls.DISTRIBUTED_CACHE_SIZE, 1), 3)
        }

# Pool d'objets pour optimiser les allocations mémoire
class OrbitalIdentityPool:
    """Pool d'objets réutilisables pour éviter les allocations coûteuses"""
    _pool = []
    _max_size = OrbsConfig.POOL_MAX_SIZE
    
    @classmethod
    def get_instance(cls, **kwargs):
        """Récupère une instance du pool ou en crée une nouvelle"""
        if cls._pool:
            instance = cls._pool.pop()
            # Réinitialiser l'instance
            for key, value in kwargs.items():
                setattr(instance, key, value)
            if hasattr(instance, '_calculate_derived_properties'):
                instance._calculate_derived_properties()
            return instance
        else:
            return OrbitalIdentity(**kwargs)
    
    @classmethod
    def return_instance(cls, instance):
        """Retourne une instance au pool"""
        if len(cls._pool) < cls._max_size:
            # Nettoyer les caches
            if hasattr(instance, 'signature_vector'):
                instance.signature_vector.cache_clear()
            if hasattr(instance, 'signature_hash'):
                instance.signature_hash.cache_clear()
            cls._pool.append(instance)

class OrbitalLayer:
    def __init__(self, name="Layer0", identities=None, metadata=None):
        self.name = name
        self.identities = identities if identities is not None else []
        self.meta = metadata if metadata is not None else {
            "type": "generic",
            "context": None,
            "tags": []
        }
        # Cache pour optimiser les opérations fréquentes
        self._cached_summary = None
        self._cache_dirty = True

    def add_identity(self, identity):
        self.identities.append(identity)
        self._cache_dirty = True

    def get_all(self):
        return self.identities

    def compress_layer(self):
        compressed, table = OrbitalIdentity.compress_symbolically(self.identities)
        return compressed, table

    def export_layer_csv(self, filename):
        return OrbitalIdentity.save_reconstructed_to_csv(self.identities, filename)

    def export_layer_json(self, filename):
        return OrbitalIdentity.save_reconstructed_to_json(self.identities, filename)

    def invalidate_cache(self):
        """Invalide le cache des résumés"""
        self._cache_dirty = True
        self._cached_summary = None

    def summary(self):
        """Résumé optimisé avec mise en cache"""
        if not self._cache_dirty and self._cached_summary is not None:
            return self._cached_summary
            
        if not self.identities:
            self._cached_summary = {
                "name": self.name,
                "count": 0,
                "i_range": (0, 0),
                "t_range": (0.0, 0.0),
                "meta": self.meta
            }
        else:
            i_values = [o.i for o in self.identities]
            t_values = [o.t for o in self.identities]
            self._cached_summary = {
                "name": self.name,
                "count": len(self.identities),
                "i_range": (min(i_values), max(i_values)),
                "t_range": (min(t_values), max(t_values)),
                "meta": self.meta
            }
        
        self._cache_dirty = False
        return self._cached_summary

class LayerMapper:
    def __init__(self):
        self.transforms = []

    def map_layer(self, source_layer, transform_fn, name_suffix="_mapped"):
        new_identities = [transform_fn(orb) for orb in source_layer.get_all() if transform_fn(orb) is not None]
        new_layer = OrbitalLayer(name=source_layer.name + name_suffix, identities=new_identities)
        self.transforms.append((source_layer.name, new_layer.name, transform_fn.__name__))
        return new_layer

    def get_history(self):
        return self.transforms

def simplify_orbit(orb):
    new_orb = copy.deepcopy(orb)
    new_orb.x = round(orb.x, 2)
    new_orb.y = round(orb.y, 2)
    new_orb.t = round(orb.t, 2)
    new_orb.alpha_deg = round(orb.alpha_deg, 1)
    return new_orb

def project_to_temporal_band(orb, band_width=1.0):
    new_orb = copy.deepcopy(orb)
    new_orb.t = round(orb.t / band_width) * band_width
    return new_orb

def quantize_angle(orb, steps=8):
    new_orb = copy.deepcopy(orb)
    step_size = 360 / steps
    new_orb.alpha_deg = round(orb.alpha_deg / step_size) * step_size
    return new_orb

def filter_by_radius(orb, min_r=0.5, max_r=1.5):
    r = math.hypot(orb.x, orb.y)
    return orb if min_r <= r <= max_r else None

def apply_and_display_layer_transforms(base_layer):
    mapper = LayerMapper()

    simplified_layer = mapper.map_layer(base_layer, simplify_orbit, "_simplified")
    temporal_layer = mapper.map_layer(base_layer, project_to_temporal_band, "_temporal")
    quantized_layer = mapper.map_layer(base_layer, quantize_angle, "_quantized")

    filtered_orbs = [o for o in base_layer.get_all() if filter_by_radius(o)]
    filtered_layer = OrbitalLayer(name=base_layer.name + "_filtered", identities=filtered_orbs)

    print("=== Layer Summaries ===")
    for layer in [simplified_layer, temporal_layer, quantized_layer, filtered_layer]:
        print(layer.summary())

    return {
        "simplified": simplified_layer,
        "temporal": temporal_layer,
        "quantized": quantized_layer,
        "filtered": filtered_layer
    }

def plot_layers(layers_dict):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = {
        "simplified": "blue",
        "temporal": "green",
        "quantized": "orange",
        "filtered": "red",
        "synthesized": "black"
    }
    for key, layer in layers_dict.items():
        xs = [o.x for o in layer.get_all()]
        ys = [o.y for o in layer.get_all()]
        ax.scatter(xs, ys, label=key, s=20, alpha=0.6, color=colors.get(key, "gray"))
    ax.set_title("Overlay of Transformed Orbital Layers")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

def analyze_differences_to_synthesized(layers_dict, synthesized_layer):
    print("=== Δ Comparaison with Synthesized Layer ===")
    from statistics import mean
    for name, layer in layers_dict.items():
        dx_list, dy_list, dt_list = [], [], []
        common = min(len(layer.get_all()), len(synthesized_layer.get_all()))
        for i in range(common):
            li = layer.get_all()[i]
            si = synthesized_layer.get_all()[i]
            dx = abs(li.x - si.x)
            dy = abs(li.y - si.y)
            dt = abs(li.t - si.t)
            dx_list.append(dx)
            dy_list.append(dy)
            dt_list.append(dt)
        print(f"{name} → Δx={mean(dx_list):.4f}, Δy={mean(dy_list):.4f}, Δt={mean(dt_list):.4f}")

def synthesize_layer_weighted(layers_dict, weights):
    """Synthèse optimisée de layer avec pondération"""
    if not layers_dict or not weights:
        return OrbitalLayer(name="synthesized_weighted", identities=[])
        
    keys = list(layers_dict.keys())
    if not keys:
        return OrbitalLayer(name="synthesized_weighted", identities=[])
        
    common_len = min(len(layers_dict[k].get_all()) for k in keys)
    if common_len == 0:
        return OrbitalLayer(name="synthesized_weighted", identities=[])
    
    synthesized = []
    total_w = sum(weights.values())
    
    if total_w == 0:
        return OrbitalLayer(name="synthesized_weighted", identities=[])
    
    for i in range(common_len):
        # Calculs vectorisés avec gestion d'erreur
        try:
            x_vals = [layers_dict[k].get_all()[i].x * weights.get(k, 0) for k in keys]
            y_vals = [layers_dict[k].get_all()[i].y * weights.get(k, 0) for k in keys]
            t_vals = [layers_dict[k].get_all()[i].t * weights.get(k, 0) for k in keys]
            alpha_vals = [layers_dict[k].get_all()[i].alpha_deg * weights.get(k, 0) for k in keys]
            
            x = sum(x_vals) / total_w
            y = sum(y_vals) / total_w
            t = sum(t_vals) / total_w
            alpha = sum(alpha_vals) / total_w
            
            base_orb = layers_dict[keys[0]].get_all()[i]
            new_orb = copy.deepcopy(base_orb)
            new_orb.x = x
            new_orb.y = y
            new_orb.t = t
            new_orb.alpha_deg = alpha
            synthesized.append(new_orb)
        except (IndexError, AttributeError, ZeroDivisionError) as e:
            logger.warning(f"Erreur lors de la synthèse à l'index {i}: {e}")
            continue
            
    return OrbitalLayer(name="synthesized_weighted", identities=synthesized)

def compute_weights_by_entropy(layers_dict):
    """Calcul optimisé des poids basés sur l'entropie"""
    def entropy(values):
        if not values:
            return 0.0
        counts = Counter(values)
        total = len(values)
        return -sum((c/total) * math.log2(c/total) for c in counts.values())

    raw_entropies = {}
    for name, layer in layers_dict.items():
        coords = [(round(o.x, 2), round(o.y, 2)) for o in layer.get_all()]
        raw_entropies[name] = entropy(coords)

    max_entropy = max(raw_entropies.values()) if raw_entropies else 1.0
    weights = {k: (max_entropy - e + 1e-6) for k, e in raw_entropies.items()}
    total = sum(weights.values())
    normalized = {k: v / total for k, v in weights.items()} if total > 0 else weights
    return normalized

def full_entropy_weighted_pipeline(base_layer):
    layers = apply_and_display_layer_transforms(base_layer)
    weights = compute_weights_by_entropy(layers)
    print("\n=== Entropy-Based Weights ===")
    for k, w in weights.items():
        print(f"{k}: {w:.4f}")
    synth = synthesize_layer_weighted(layers, weights)
    analyze_differences_to_synthesized(layers, synth)
    plot_layers({**layers, "synthesized": synth})
    return synth

class OrbitalDecoder:
    @staticmethod
    def decode_from_layer(synthesized_layer):
        print("\n=== Decoded Orbital Identities ===")
        for idx, orb in enumerate(synthesized_layer.get_all()):
            print(f"#{idx}: (x={orb.x:.2f}, y={orb.y:.2f}, t={orb.t:.2f}, alpha={orb.alpha_deg:.1f}°)")
        return synthesized_layer.get_all()

    @staticmethod
    def export_to_text(synthesized_layer, filename="decoded_output.txt"):
        with open(filename, "w") as f:
            for orb in synthesized_layer.get_all():
                line = f"x={orb.x:.3f}, y={orb.y:.3f}, t={orb.t:.3f}, alpha={orb.alpha_deg:.1f}°\n"
                f.write(line)
        print(f"Decoded data saved to {filename}")

    @staticmethod
    def reconstruct_original_format(synthesized_layer, template_orbit_class):
        reconstructed = []
        for orb in synthesized_layer.get_all():
            new_orb = template_orbit_class(
                i=getattr(orb, 'i', 0),
                x=orb.x,
                y=orb.y,
                t=orb.t,
                alpha_deg=orb.alpha_deg
            )
            reconstructed.append(new_orb)
        return reconstructed

    @staticmethod
    def evaluate_reconstruction(original_orbs, reconstructed_orbs):
        if len(original_orbs) != len(reconstructed_orbs):
            print("Warning: Length mismatch between original and reconstructed identities.")

        total = min(len(original_orbs), len(reconstructed_orbs))
        dxs, dys, dts, dalphas = [], [], [], []

        for i in range(total):
            orig = original_orbs[i]
            recon = reconstructed_orbs[i]
            dxs.append(abs(orig.x - recon.x))
            dys.append(abs(orig.y - recon.y))
            dts.append(abs(orig.t - recon.t))
            dalphas.append(abs(orig.alpha_deg - recon.alpha_deg))

        def avg(lst): return sum(lst) / len(lst) if lst else 0.0

        return {
            "Δx_mean": avg(dxs),
            "Δy_mean": avg(dys),
            "Δt_mean": avg(dts),
            "Δalpha_mean": avg(dalphas)
        }

class OrbitalIdentity:
    """
    Identité orbitale optimisée avec gestion mémoire efficace
    """
    __slots__ = ('i', 'delta', 'Z', 'delta_t', 'R', 'Cx', 'Cy', 'sigma', 'epsilon', 's',
                 'x', 'y', 't', 'alpha_deg', 'xi_comp', 'yi_comp', '_signature_cache')
    
    def __init__(self, i: int, delta: int, Z: int, delta_t: float, R: float = 1.0, Cx: float = 0.0, Cy: float = 0.0, sigma: float = 0.0, epsilon: float = 0.05, s: float = 1.0):
        # Validation des paramètres critiques
        if not isinstance(i, int) or i < 0:
            raise ValueError(f"Parameter 'i' must be a non-negative integer, got {i}")
        if not isinstance(Z, int) or Z <= 0:
            raise ValueError(f"Parameter 'Z' must be a positive integer, got {Z}")
        if delta_t <= 0:
            raise ValueError(f"Parameter 'delta_t' must be positive, got {delta_t}")
        if R <= 0:
            raise ValueError(f"Parameter 'R' must be positive, got {R}")
        
        self.i = i
        self.delta = delta
        self.Z = Z
        self.delta_t = delta_t
        self.R = R
        self.Cx = Cx
        self.Cy = Cy
        self.sigma = sigma
        self.epsilon = epsilon
        self.s = s
        
        # Propriétés calculées manquantes
        self._signature_cache = {}  # Cache manuel plus rapide
        self._calculate_derived_properties()
    
    def _calculate_derived_properties(self):
        """Calcule les propriétés dérivées x, y, t, alpha_deg, etc."""
        if hasattr(self, 'i') and hasattr(self, 'delta_t'):
            self.t = self.i * self.delta_t
            self.alpha_deg = (self.i * 360 / self.Z) % 360 if self.Z != 0 else 0.0
            alpha_rad = math.radians(self.alpha_deg)
            self.x = self.R * math.cos(alpha_rad) + self.Cx
            self.y = self.R * math.sin(alpha_rad) + self.Cy
            # Ajout des composantes xi_comp et yi_comp manquantes
            self.xi_comp = self.x * math.cos(alpha_rad) - self.y * math.sin(alpha_rad)
            self.yi_comp = self.x * math.sin(alpha_rad) + self.y * math.cos(alpha_rad)

    def signature_vector(self):
        """Retourne un vecteur de signature pour la compression symbolique."""
        if 'vector' not in self._signature_cache:
            self._signature_cache['vector'] = (self.alpha_deg, self.t, self.x, self.y)
        return self._signature_cache['vector']
    
    def signature_hash(self):
        """Retourne un hash unique pour l'identité orbitale."""
        if 'hash' not in self._signature_cache:
            import hashlib
            sig_str = f"{self.i}_{self.alpha_deg:.6f}_{self.x:.6f}_{self.y:.6f}_{self.t:.6f}"
            self._signature_cache['hash'] = hashlib.md5(sig_str.encode()).hexdigest()[:8]
        return self._signature_cache['hash']
    
    def get_metadata(self):
        """Retourne les métadonnées de l'orbite pour l'export JSON."""
        return {
            "i": self.i,
            "delta": self.delta,
            "Z": self.Z,
            "delta_t": self.delta_t,
            "R": self.R,
            "Cx": self.Cx,
            "Cy": self.Cy,
            "sigma": self.sigma,
            "epsilon": self.epsilon,
            "s": self.s,
            "x": self.x,
            "y": self.y,
            "t": self.t,
            "alpha_deg": self.alpha_deg,
            "xi_comp": self.xi_comp,
            "yi_comp": self.yi_comp
        }
    
    def __eq__(self, other):
        """Comparaison d'égalité entre deux OrbitalIdentity"""
        if not isinstance(other, OrbitalIdentity):
            return False
        return (self.i == other.i and self.delta == other.delta and 
                self.Z == other.Z and abs(self.delta_t - other.delta_t) < 1e-10)
    
    def __hash__(self):
        """Hash pour utilisation dans des sets/dict"""
        return hash((self.i, self.delta, self.Z, round(self.delta_t, 10)))
    
    def __lt__(self, other):
        """Comparaison pour tri par temps"""
        if not isinstance(other, OrbitalIdentity):
            return NotImplemented
        return self.t < other.t

    @staticmethod
    def filter_by_region(identities, center, radius):
        """Filtre les identités dans une région circulaire centrée en 'center' de rayon 'radius'."""
        if not identities:
            return []
        if not isinstance(center, (tuple, list)) or len(center) != 2:
            raise ValueError("Parameter 'center' must be a tuple/list of 2 elements")
        if radius <= 0:
            raise ValueError(f"Parameter 'radius' must be positive, got {radius}")
        
        cx, cy = center
        radius_squared = radius * radius  # Éviter sqrt() dans la boucle
        
        # Pré-filtrage rapide par bounding box pour les grandes listes
        if len(identities) > 100:
            min_x, max_x = cx - radius, cx + radius
            min_y, max_y = cy - radius, cy + radius
            candidates = [orb for orb in identities 
                         if min_x <= orb.x <= max_x and min_y <= orb.y <= max_y]
            return [orb for orb in candidates 
                    if (orb.x - cx)**2 + (orb.y - cy)**2 <= radius_squared]
        else:
            return [orb for orb in identities if (orb.x - cx)**2 + (orb.y - cy)**2 <= radius_squared]

    @staticmethod
    def find_nearest_orbit(identities: List['OrbitalIdentity'], target: 'OrbitalIdentity') -> Optional['OrbitalIdentity']:
        """Trouve l'identité la plus proche de 'target' dans la liste 'identities'."""
        if not identities:
            return None
            
        best_orb = None
        best_dist = float("inf")
        for orb in identities:
            # Utilisation de la distance euclidienne au carré pour éviter sqrt()
            dist_squared = (orb.x - target.x)**2 + (orb.y - target.y)**2
            if dist_squared < best_dist:
                best_dist = dist_squared
                best_orb = orb
        return best_orb

    @staticmethod
    def detect_temporal_collisions(identities, epsilon_t=1e-3):
        """Détecte les collisions temporelles entre identités (écart < epsilon_t)."""
        collisions = []
        sorted_orbits = sorted(identities, key=lambda o: o.t)
        for i in range(len(sorted_orbits) - 1):
            if abs(sorted_orbits[i].t - sorted_orbits[i+1].t) < epsilon_t:
                collisions.append((sorted_orbits[i], sorted_orbits[i+1]))
        return collisions

    @staticmethod
    def simulate_orbit_plot(identities, color='green'):
        """Affiche la trajectoire simulée des identités orbitales sur un graphique."""
        fig, ax = plt.subplots()
        for orb in identities:
            ax.plot(orb.x, orb.y, 'o', color=color)
        ax.set_aspect('equal')
        ax.set_title("Simulated Orbit Trajectory")
        plt.show()

    @staticmethod
    def export_to_csv(identities, filename="orbits.csv"):
        """Exporte les identités orbitales dans un fichier CSV."""
        with open(filename, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["i", "x", "y", "alpha", "t"])
            for orb in identities:
                writer.writerow([orb.i, orb.x, orb.y, orb.alpha_deg, orb.t])

    @staticmethod
    def animate_orbits(identities, interval=100):
        fig, ax = plt.subplots()
        ax.set_xlim(-2, 2)
        ax.set_ylim(-2, 2)
        ax.set_aspect('equal')
        point, = ax.plot([], [], 'ro')

        def update(frame):
            orb = identities[frame % len(identities)]
            point.set_data(orb.x, orb.y)
            return point,

        ani = animation.FuncAnimation(fig, update, frames=len(identities), interval=interval, blit=True)
        plt.show()

    @staticmethod
    def group_synchronous(identities, epsilon_t=1e-3):
        groups = []
        current = []
        sorted_orbits = sorted(identities, key=lambda o: o.t)
        for orb in sorted_orbits:
            if not current:
                current.append(orb)
            elif abs(orb.t - current[-1].t) < epsilon_t:
                current.append(orb)
            else:
                if len(current) > 1:
                    groups.append(current)
                current = [orb]
        if len(current) > 1:
            groups.append(current)
        return groups

    @staticmethod
    def extract_sync_representatives(groups):
        return [group[0] for group in groups]

    @staticmethod
    def merge_synchronous(groups):
        merged = []
        for group in groups:
            if group:
                cx = sum(o.x for o in group) / len(group)
                cy = sum(o.y for o in group) / len(group)
                avg_i = sum(o.i for o in group) // len(group)
                base = group[0]
                merged.append(OrbitalIdentity(
                    i=avg_i, delta=base.delta, Z=base.Z, delta_t=base.delta_t,
                    R=base.R, Cx=cx, Cy=cy, sigma=base.sigma, epsilon=base.epsilon, s=base.s
                ))
        return merged


    @staticmethod
    def compress_symbolically(identities):
        symbol_table = {}
        compressed = []
        counter = 0
        for orb in identities:
            sig = tuple(orb.signature_vector())
            if sig not in symbol_table:
                symbol_table[sig] = f"S{counter}"
                counter += 1
            compressed.append(symbol_table[sig])
        return compressed, symbol_table

    @staticmethod
    def divergence_grid(identities, reference):
        grid = []
        for orb in identities:
            dx = orb.x - reference.x
            dy = orb.y - reference.y
            dt = orb.t - reference.t
            angle_diff = (orb.alpha_deg - reference.alpha_deg) % 360
            grid.append({
                "dx": round(dx, 6),
                "dy": round(dy, 6),
                "dt": round(dt, 6),
                "d_angle": round(angle_diff, 6),
                "target_id": orb.signature_hash()
            })
        return grid


    @staticmethod
    def similarity_matrix_vectorized(identities, normalized=True):
        """Calcul vectorisé ultra-rapide de la matrice de similarité"""
        try:
            import numpy as np
            n = len(identities)
            if n == 0:
                return []
            
            # Extraction vectorisée des coordonnées
            coords = np.array([[o.x, o.y, o.t, o.alpha_deg] for o in identities])
            
            # Calcul matriciel des distances
            diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
            
            # Gestion de la distance angulaire circulaire
            angle_diff = diff[:, :, 3]
            angle_diff = np.minimum(np.abs(angle_diff), 360 - np.abs(angle_diff))
            diff[:, :, 3] = angle_diff
            
            # Distance euclidienne vectorisée
            distances = np.sqrt(np.sum(diff**2, axis=2))
            
            # Normalisation optionnelle
            if normalized:
                max_dist = np.max(distances)
                if max_dist > 0:
                    distances = distances / max_dist
            
            return distances.round(6).tolist()
            
        except ImportError:
            # Fallback vers l'implémentation standard
            logger.warning("NumPy non disponible, utilisation de l'implémentation standard")
            return OrbitalIdentity.similarity_matrix_fallback(identities, normalized, cache_enabled=True)

    @staticmethod
    def similarity_matrix_fallback(identities, normalized=True, cache_enabled=True):
        """Calcule la matrice de similarité avec optimisations (fallback)"""
        n = len(identities)
        if n == 0:
            return []
            
        matrix = [[0.0 for _ in range(n)] for _ in range(n)]
        
        # Cache pour éviter les recalculs symétriques
        if cache_enabled:
            distance_cache = {}
        
        max_distance = 0.0  # Pour la normalisation
        
        for i in range(n):
            for j in range(i, n):  # Optimisation : matrice symétrique
                if i == j:
                    matrix[i][j] = 0.0
                else:
                    # Vérifier le cache pour la paire (i,j) ou (j,i)
                    cache_key = (min(i, j), max(i, j))
                    
                    if cache_enabled and cache_key in distance_cache:
                        distance = distance_cache[cache_key]
                    else:
                        # Calcul optimisé de la distance
                        orb_i, orb_j = identities[i], identities[j]
                        dx = orb_i.x - orb_j.x
                        dy = orb_i.y - orb_j.y
                        dt = orb_i.t - orb_j.t
                        d_angle = min(
                            abs(orb_i.alpha_deg - orb_j.alpha_deg),
                            360 - abs(orb_i.alpha_deg - orb_j.alpha_deg)
                        )  # Distance angulaire circulaire optimisée
                        
                        distance = math.sqrt(dx**2 + dy**2 + dt**2 + d_angle**2)
                        
                        if cache_enabled:
                            distance_cache[cache_key] = distance
                    
                    matrix[i][j] = round(distance, 6)
                    matrix[j][i] = matrix[i][j]  # Symétrie
                    max_distance = max(max_distance, distance)
        
        # Normalisation optionnelle
        if normalized and max_distance > 0:
            for i in range(n):
                for j in range(n):
                    if i != j:
                        matrix[i][j] = round(matrix[i][j] / max_distance, 6)
        
        return matrix

    @staticmethod
    def compress_topologically(identities, epsilon=0.01):
        """Compression topologique optimisée avec spatial indexing"""
        if not identities:
            return []
            
        chains = []
        visited = set()
        
        # Optimisation : trier les orbites par position pour améliorer la localité
        sorted_orbs = sorted(identities, key=lambda o: (o.x, o.y))
        
        for orb in sorted_orbs:
            if orb in visited:
                continue
                
            chain = [orb]
            visited.add(orb)
            current = orb
            
            while True:
                # Optimisation : utiliser distance au carré pour éviter sqrt()
                epsilon_squared = epsilon * epsilon
                candidates = [o for o in identities if o not in visited]
                
                if not candidates:
                    break
                    
                # Trouver le plus proche avec distance optimisée
                next_orb = None
                min_dist_sq = float('inf')
                
                for candidate in candidates:
                    dist_sq = (candidate.x - current.x)**2 + (candidate.y - current.y)**2
                    if dist_sq < min_dist_sq:
                        min_dist_sq = dist_sq
                        next_orb = candidate
                
                if next_orb and min_dist_sq < epsilon_squared:
                    chain.append(next_orb)
                    visited.add(next_orb)
                    current = next_orb
                else:
                    break
                    
            if len(chain) > 1:
                chains.append(chain)
                
        return chains

    @staticmethod
    def export_compressed_block(symbols, table, filename="compressed_block.json", 
                               include_metadata=True, compression_stats=True):
        """Export amélioré avec métadonnées et statistiques"""
        block = {
            "symbols": symbols,
            "table": {str(k): v for k, v in table.items()}
        }
        
        if include_metadata:
            block["metadata"] = {
                "symbol_count": len(symbols),
                "unique_symbols": len(table),
                "compression_ratio": round(len(symbols) / max(len(table), 1), 3),
                "generated_at": "2025-07-25T00:00:00Z",  # Timestamp statique pour la démo
                "format_version": "1.1"
            }
        
        if compression_stats and symbols:
            from collections import Counter
            symbol_counts = Counter(symbols)
            block["statistics"] = {
                "most_common_symbol": symbol_counts.most_common(1)[0] if symbol_counts else None,
                "symbol_frequency": dict(symbol_counts.most_common(10)),  # Top 10
                "entropy": round(-sum(
                    (count/len(symbols)) * math.log2(count/len(symbols)) 
                    for count in symbol_counts.values()
                ), 4) if len(symbols) > 0 else 0.0
            }
        
        with open(filename, "w") as f:
            json.dump(block, f, indent=OrbsConfig.JSON_INDENT)
        
        logger.info(f"Exported compressed block to {filename} "
                    f"({len(symbols)} symbols, {len(table)} unique)")
        return filename


    @staticmethod
    def reconstruct_from_symbols(symbols, table):
        """Reconstruction robuste depuis les symboles avec gestion d'erreur"""
        # La table peut contenir des clés sous différents formats
        reverse_lookup = {}
        
        for k, v in table.items():
            if isinstance(k, tuple):
                # Clé déjà en tuple
                reverse_lookup[v] = k
            elif isinstance(k, str):
                try:
                    # Parse string tuple format: "(1.0, 2.0, 3.0, 4.0)"
                    clean_k = k.strip('()')
                    if clean_k:
                        parsed = tuple(map(float, clean_k.split(',')))
                        reverse_lookup[v] = parsed
                except ValueError as e:
                    logger.warning(f"Failed to parse table key {k}: {e}")
                    continue
        
        reconstructed = []
        for sym in symbols:
            sig = reverse_lookup.get(sym)
            if not sig:
                logger.warning(f"Symbol {sym} not found in table")
                continue
                
            try:
                alpha, t, x, y = sig
                # Calcul plus robuste de delta_t et i
                if alpha != 0:
                    # Estimation basée sur la relation alpha = (i * 360 / Z) % 360
                    Z_guess = 360
                    normalized_alpha = alpha % 360
                    i_from_alpha = round(normalized_alpha * Z_guess / 360)
                    delta_t = t / i_from_alpha if i_from_alpha > 0 else 0.1
                    i_guess = max(0, i_from_alpha)
                else:
                    delta_t = 0.1  # valeur par défaut
                    i_guess = max(0, round(t / delta_t))
                
                orb = OrbitalIdentity(
                    i=i_guess,
                    delta=0,
                    Z=360,
                    delta_t=delta_t,
                    R=max(0.1, math.hypot(x, y)),  # R minimum pour éviter les erreurs
                    Cx=0.0,
                    Cy=0.0,
                    sigma=0.0,
                    epsilon=0.0,
                    s=1.0
                )
                reconstructed.append(orb)
            except (ValueError, ZeroDivisionError) as e:
                logger.error(f"Failed to reconstruct from signature {sig}: {e}")
                continue
                
        return reconstructed


    @staticmethod
    def reconstruct_approximate(symbols, table, default_delta_t=0.1, Z=360):
        # La table contient déjà des tuples comme clés, pas besoin de conversion
        reverse_lookup = {v: k for k, v in table.items()}
        reconstructed = []

        for idx, sym in enumerate(symbols):
            sig = reverse_lookup.get(sym, None)
            if sig:
                alpha, t, x, y = sig
            else:
                # Approximation fallback if symbol not in table
                alpha = (idx * 360 / Z) % 360
                t = idx * default_delta_t
                x = math.cos(math.radians(alpha))
                y = math.sin(math.radians(alpha))

            i_est = round(t / default_delta_t)
            orb = OrbitalIdentity(
                i=i_est,
                delta=0,
                Z=Z,
                delta_t=default_delta_t,
                R=math.hypot(x, y),
                Cx=0.0,
                Cy=0.0,
                sigma=0.0,
                epsilon=0.0,
                s=1.0
            )
            reconstructed.append(orb)

        return reconstructed


    @staticmethod
    def evaluate_reconstruction(originals, reconstructed, tolerance=1e-3):
        """Évalue la qualité de la reconstruction (vectorisé et optimisé)"""
        if len(originals) != len(reconstructed):
            logger.warning("Mismatch in sequence length")
            
        total = min(len(originals), len(reconstructed))
        if total == 0:
            return {"avg_dx": 0, "avg_dy": 0, "avg_dt": 0, "avg_dalpha": 0, "failed_reconstructions": 0, "total": 0}
        
        # Vectorisation des calculs de différences
        dx_values = [abs(o.x - r.x) for o, r in zip(originals[:total], reconstructed[:total])]
        dy_values = [abs(o.y - r.y) for o, r in zip(originals[:total], reconstructed[:total])]
        dt_values = [abs(o.t - r.t) for o, r in zip(originals[:total], reconstructed[:total])]
        da_values = [abs((o.alpha_deg - r.alpha_deg) % 360) for o, r in zip(originals[:total], reconstructed[:total])]
        
        # Calcul vectorisé des échecs
        failed = sum(1 for dx, dy, dt in zip(dx_values, dy_values, dt_values) 
                    if dx > tolerance or dy > tolerance or dt > tolerance)
        
        return {
            "avg_dx": round(sum(dx_values) / total, 6),
            "avg_dy": round(sum(dy_values) / total, 6),
            "avg_dt": round(sum(dt_values) / total, 6),
            "avg_dalpha": round(sum(da_values) / total, 6),
            "failed_reconstructions": failed,
            "total": total
        }

    @staticmethod
    def verify_reconstruction(originals, reconstructed, strict=False):
        """Vérifie la reconstruction : stricte (hash) ou tolérante (écarts faibles)."""
        for o, r in zip(originals, reconstructed):
            if strict:
                if o.signature_hash() != r.signature_hash():
                    return False
            else:
                dx = abs(o.x - r.x)
                dy = abs(o.y - r.y)
                dt = abs(o.t - r.t)
                if dx > 1e-3 or dy > 1e-3 or dt > 1e-3:
                    return False
        return True

    @staticmethod
    def save_reconstructed_to_json(identities, filename="reconstructed.json"):
        data = [orb.get_metadata() for orb in identities]
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        return filename

    @staticmethod
    def save_reconstructed_to_csv(identities, filename="reconstructed.csv"):
        with open(filename, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["i", "x", "y", "alpha", "t", "xi_comp", "yi_comp"])
            for orb in identities:
                writer.writerow([
                    orb.i, orb.x, orb.y, orb.alpha_deg, orb.t, orb.xi_comp, orb.yi_comp
                ])
        return filename


    @staticmethod
    def detect_anomalies(originals, reconstructed, tolerance=1e-3):
        """Détection d'anomalies avec analyse statistique"""
        anomalies = []
        all_dx, all_dy, all_dt, all_da = [], [], [], []
        
        for o, r in zip(originals, reconstructed):
            dx = abs(o.x - r.x)
            dy = abs(o.y - r.y)
            dt = abs(o.t - r.t)
            da = abs((o.alpha_deg - r.alpha_deg) % 360)
            
            all_dx.append(dx)
            all_dy.append(dy)  
            all_dt.append(dt)
            all_da.append(da)
            
            if dx > tolerance or dy > tolerance or dt > tolerance:
                anomalies.append({
                    "i": o.i,
                    "dx": round(dx, 6),
                    "dy": round(dy, 6),
                    "dt": round(dt, 6),
                    "dalpha": round(da, 6),
                    "severity": round(max(dx, dy, dt) / tolerance, 2),
                    "x_original": o.x,
                    "y_original": o.y,
                    "t_original": o.t,
                    "x_recon": r.x,
                    "y_recon": r.y,
                    "t_recon": r.t
                })
        
        # Statistiques globales
        def safe_mean(lst): return sum(lst) / len(lst) if lst else 0.0
        def safe_std(lst): 
            if len(lst) < 2: return 0.0
            mean_val = safe_mean(lst)
            return math.sqrt(sum((x - mean_val)**2 for x in lst) / (len(lst) - 1))
        
        stats = {
            "total_pairs": len(originals),
            "anomalies_count": len(anomalies),
            "anomaly_rate": round(len(anomalies) / max(len(originals), 1), 4),
            "error_stats": {
                "dx_mean": round(safe_mean(all_dx), 6),
                "dy_mean": round(safe_mean(all_dy), 6),
                "dt_mean": round(safe_mean(all_dt), 6),
                "dx_std": round(safe_std(all_dx), 6),
                "dy_std": round(safe_std(all_dy), 6),
                "dt_std": round(safe_std(all_dt), 6)
            }
        }
        
        return {
            "anomalies": anomalies,
            "statistics": stats
        }

    @staticmethod
    def analyze_orbital_patterns(identities, window_size=10):
        """Analyse des patterns orbitaux avec fenêtre glissante"""
        if len(identities) < window_size:
            return {"error": "Not enough identities for pattern analysis"}
        
        patterns = []
        sorted_orbs = sorted(identities, key=lambda o: o.t)
        
        for i in range(len(sorted_orbs) - window_size + 1):
            window = sorted_orbs[i:i + window_size]
            
            # Analyse des tendances dans la fenêtre
            x_trend = (window[-1].x - window[0].x) / window_size
            y_trend = (window[-1].y - window[0].y) / window_size
            alpha_changes = [
                abs(window[j].alpha_deg - window[j-1].alpha_deg) 
                for j in range(1, len(window))
            ]
            
            pattern = {
                "window_start": i,
                "time_range": (window[0].t, window[-1].t),
                "x_trend": round(x_trend, 6),
                "y_trend": round(y_trend, 6),
                "avg_alpha_change": round(sum(alpha_changes) / len(alpha_changes), 2),
                "max_alpha_change": round(max(alpha_changes), 2),
                "pattern_type": "linear" if abs(x_trend) > 1e-3 or abs(y_trend) > 1e-3 else "stable"
            }
            patterns.append(pattern)
        
        return {
            "total_windows": len(patterns),
            "patterns": patterns,
            "summary": {
                "linear_patterns": len([p for p in patterns if p["pattern_type"] == "linear"]),
                "stable_patterns": len([p for p in patterns if p["pattern_type"] == "stable"])
            }
        }

    @staticmethod
    def performance_benchmark(identities_count=1000, iterations=10):
        """Benchmark de performance intégré et optimisé"""
        # Génération optimisée de données de test
        test_identities = [
            OrbitalIdentity(i=i, delta=0, Z=3600, delta_t=0.01) 
            for i in range(identities_count)
        ]
        
        results = {}
        
        # Test 1: Filtrage par région
        start = time.time()
        for _ in range(iterations):
            filtered = OrbitalIdentity.filter_by_region(test_identities, (0, 0), 1.0)
        elapsed = time.time() - start
        results['filter_region'] = {
            'time_per_iter': round(elapsed / iterations, 6),
            'throughput': round(identities_count * iterations / max(elapsed, 1e-6), 0),
            'filtered_count': len(filtered) if filtered else 0
        }
        
        # Test 2: Recherche du plus proche
        target = test_identities[identities_count // 2]
        start = time.time()
        for _ in range(iterations):
            nearest = OrbitalIdentity.find_nearest_orbit(test_identities, target)
        elapsed = time.time() - start
        results['find_nearest'] = {
            'time_per_iter': round(elapsed / iterations, 6),
            'throughput': round(identities_count * iterations / max(elapsed, 1e-6), 0),
            'found': nearest is not None
        }
        
        # Test 3: Compression symbolique
        start = time.time()
        sample_size = min(100, identities_count)
        sample = test_identities[:sample_size]
        for _ in range(iterations):
            compressed, table = OrbitalIdentity.compress_symbolically(sample)
        elapsed = time.time() - start
        results['compression'] = {
            'time_per_iter': round(elapsed / iterations, 6),
            'compression_ratio': round(len(compressed) / max(len(table), 1), 2) if compressed and table else 0,
            'sample_size': sample_size
        }
        
        # Test 4: Matrice de similarité vectorisée
        small_sample = test_identities[:min(50, identities_count)]
        start = time.time()
        try:
            matrix = OrbitalIdentity.similarity_matrix_vectorized(small_sample, normalized=True)
            success = True
        except Exception as e:
            logger.warning(f"Erreur matrice vectorisée: {e}")
            matrix = []
            success = False
        elapsed = time.time() - start
        results['similarity_matrix'] = {
            'time': round(elapsed, 6),
            'matrix_size': f"{len(matrix)}x{len(matrix[0]) if matrix else 0}",
            'vectorized_success': success,
            'sample_size': len(small_sample)
        }
        
        return {
            "benchmark_config": {
                "identities_count": identities_count,
                "iterations": iterations,
                "timestamp": time.time()
            },
            "results": results,
            "summary": {
                "fastest_operation": min(results.keys(), 
                                       key=lambda k: results[k].get('time_per_iter', 
                                                                   results[k].get('time', float('inf')))),
                "total_benchmark_time": round(sum(
                    r.get('time_per_iter', r.get('time', 0)) * (iterations if 'time_per_iter' in r else 1)
                    for r in results.values()
                ), 3),
                "all_tests_passed": all(
                    r.get('filtered_count', 0) >= 0 and
                    r.get('found', True) and 
                    r.get('compression_ratio', 0) >= 0 and
                    r.get('vectorized_success', True)
                    for r in results.values()
                )
            }
        }

 
    def __repr__(self):
        return (f"OrbitalIdentity(i={self.i}, delta={self.delta}, Z={self.Z}, delta_t={self.delta_t}, "
                f"R={self.R}, Cx={self.Cx}, Cy={self.Cy}, sigma={self.sigma}, epsilon={self.epsilon}, s={self.s})")


def main_benchmark():
    """Point d'entrée pour l'exécutable orbs-benchmark"""
    import sys
    try:
        n_orbits = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
        iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        
        print(f"🚀 ORBS ULTRA - Benchmark de Performance")
        print(f"Orbites: {n_orbits}, Itérations: {iterations}")
        print("=" * 50)
        
        results = OrbitalIdentity.performance_benchmark(n_orbits, iterations)
        
        print(f"\n🏆 Benchmark terminé avec succès!")
        print(f"📊 Temps moyen par orbite: {results.get('avg_time_per_orbit', 0):.6f}s")
        
    except Exception as e:
        print(f"❌ Erreur lors du benchmark: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Si exécuté directement, lancer le benchmark
    main_benchmark()